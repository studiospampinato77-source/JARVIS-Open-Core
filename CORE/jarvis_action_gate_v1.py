"""JARVIS Action Gate V1 — human-approved outbound actions with a tamper-evident audit log.

The same rules the private JARVIS uses for its daily email outreach, as a small reusable engine:

    prepare  ->  PENDING_APPROVAL   (the agent proposes; nothing leaves)
    approve  ->  APPROVED           (a human approves THIS exact content, bound by SHA-256)
    execute  ->  EXECUTED           (only if still approved, unchanged, under the daily limit,
                                     recipient not opted out, kill switch off)

- Executors are pluggable. The default OutboxExecutor writes a real .eml file into a local
  outbox folder instead of sending: the demo and the tests never touch the network.
- Opt-out: a recipient who answered "NO" is refused at prepare time and again at execute time.
- Kill switch: if the STOP file exists in the gate folder, nothing executes.
- Audit log: every event is appended to audit.jsonl; each line carries the hash of the previous
  one, so editing or deleting a past line is detected by verify_audit().
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Dict, Optional

KNOWN_KINDS = {"email", "message", "publish", "payment"}
GENESIS = "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_hash(kind: str, payload: dict) -> str:
    body = json.dumps({"kind": str(kind or "").lower(), "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class GateError(Exception):
    """Raised when an action is refused. `code` is a stable machine-readable reason."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class OutboxExecutor:
    """Writes emails as .eml files into a local folder. Never sends anything."""

    def __init__(self, outbox: Path, sender: str = "agent@example.org"):
        self.outbox = Path(outbox)
        self.sender = sender

    def __call__(self, action: dict) -> dict:
        p = action["payload"]
        msg = EmailMessage(policy=policy.default.clone(max_line_length=200))  # keep the 64-char hash on one line
        msg["From"] = self.sender
        msg["To"] = p["to"]
        msg["Subject"] = p.get("subject", "")
        msg["X-Action-Id"] = action["id"]
        msg["X-Action-Hash"] = action["hash"]
        msg.set_content(p.get("body", ""))
        self.outbox.mkdir(parents=True, exist_ok=True)
        path = self.outbox / f"{action['id']}.eml"
        path.write_bytes(bytes(msg))
        return {"delivered_to": "LOCAL_OUTBOX", "file": str(path)}


class ActionGate:
    def __init__(self, root: Optional[Path] = None, daily_limits: Optional[Dict[str, int]] = None,
                 executors: Optional[Dict[str, Callable[[dict], dict]]] = None):
        self.root = Path(root or Path(os.getenv("JARVIS_DATA_DIR", "data")) / "action_gate")
        self.actions_dir = self.root / "actions"
        self.audit_path = self.root / "audit.jsonl"
        self.optout_path = self.root / "opt_out.json"
        self.stop_path = self.root / "STOP"
        self.daily_limits = {"email": 25, "message": 25, "publish": 2, "payment": 0, **(daily_limits or {})}
        self.executors = {"email": OutboxExecutor(self.root / "outbox"), **(executors or {})}
        self.actions_dir.mkdir(parents=True, exist_ok=True)

    # ---------- storage ----------
    def _path(self, action_id: str) -> Path:
        if not action_id or "/" in action_id or ".." in action_id:
            raise GateError("BAD_ACTION_ID", action_id)
        return self.actions_dir / f"{action_id}.json"

    def get(self, action_id: str) -> dict:
        p = self._path(action_id)
        if not p.exists():
            raise GateError("UNKNOWN_ACTION", action_id)
        return json.loads(p.read_text(encoding="utf-8"))

    def _save(self, action: dict) -> None:
        self._path(action["id"]).write_text(json.dumps(action, ensure_ascii=False, indent=1), encoding="utf-8")

    def _last_hash(self) -> str:
        if not self.audit_path.exists():
            return GENESIS
        last = ""
        with self.audit_path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        return json.loads(last)["entry_hash"] if last else GENESIS

    def _audit(self, event: str, action: dict, actor: str, **detail) -> None:
        entry = {"ts": _now(), "event": event, "action_id": action.get("id"), "kind": action.get("kind"),
                 "action_hash": action.get("hash"), "actor": actor, "detail": detail, "prev": self._last_hash()}
        entry["entry_hash"] = hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ---------- opt-out ----------
    def _optouts(self) -> set:
        try:
            return set(json.loads(self.optout_path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return set()

    def opt_out(self, address: str, actor: str = "recipient") -> None:
        s = self._optouts() | {address.strip().lower()}
        self.optout_path.write_text(json.dumps(sorted(s), indent=1), encoding="utf-8")
        self._audit("OPT_OUT", {}, actor, address=address.strip().lower())

    def _check_recipient(self, action: dict) -> None:
        to = str(action["payload"].get("to") or "").strip().lower()
        if to and to in self._optouts():
            raise GateError("RECIPIENT_OPTED_OUT", to)

    # ---------- lifecycle ----------
    def prepare(self, kind: str, payload: dict, proposed_by: str = "agent", reason: str = "") -> dict:
        kind = str(kind or "").lower()
        if kind not in KNOWN_KINDS:
            raise GateError("UNKNOWN_KIND", kind)
        if kind == "email" and not str(payload.get("to") or "").strip():
            raise GateError("MISSING_RECIPIENT")
        action = {"id": uuid.uuid4().hex[:12], "kind": kind, "payload": payload, "hash": content_hash(kind, payload),
                  "status": "PENDING_APPROVAL", "proposed_by": proposed_by, "reason": reason, "created_at": _now()}
        self._check_recipient(action)
        self._save(action)
        self._audit("PREPARED", action, proposed_by, reason=reason)
        return action

    def approve(self, action_id: str, approved_by: str) -> dict:
        if not str(approved_by or "").strip():
            raise GateError("APPROVER_REQUIRED")
        action = self.get(action_id)
        if action["status"] != "PENDING_APPROVAL":
            raise GateError("NOT_PENDING", action["status"])
        action.update(status="APPROVED", approved_by=approved_by, approved_at=_now(), approved_hash=action["hash"])
        self._save(action)
        self._audit("APPROVED", action, approved_by)
        return action

    def reject(self, action_id: str, rejected_by: str, why: str = "") -> dict:
        action = self.get(action_id)
        action.update(status="REJECTED", rejected_by=rejected_by, rejected_at=_now(), why=why)
        self._save(action)
        self._audit("REJECTED", action, rejected_by, why=why)
        return action

    def _executed_today(self, kind: str) -> int:
        today = _now()[:10]
        n = 0
        for p in self.actions_dir.glob("*.json"):
            a = json.loads(p.read_text(encoding="utf-8"))
            if a.get("kind") == kind and a.get("status") == "EXECUTED" and str(a.get("executed_at", "")).startswith(today):
                n += 1
        return n

    def execute(self, action_id: str, actor: str = "executor") -> dict:
        action = self.get(action_id)
        try:
            if self.stop_path.exists():
                raise GateError("KILL_SWITCH_ON", str(self.stop_path))
            if action["status"] == "EXECUTED":
                raise GateError("ALREADY_EXECUTED")
            if action["status"] != "APPROVED":
                raise GateError("NOT_APPROVED", action["status"])
            if content_hash(action["kind"], action["payload"]) != action.get("approved_hash"):
                raise GateError("CONTENT_CHANGED_AFTER_APPROVAL")
            self._check_recipient(action)
            limit = self.daily_limits.get(action["kind"], 0)
            if self._executed_today(action["kind"]) >= limit:
                raise GateError("DAILY_LIMIT_REACHED", f"{action['kind']} limit {limit}")
            executor = self.executors.get(action["kind"])
            if executor is None:
                raise GateError("NO_EXECUTOR", action["kind"])
        except GateError as e:
            self._audit("REFUSED", action, actor, code=e.code)
            raise
        result = executor(action)
        action.update(status="EXECUTED", executed_at=_now(), result=result)
        self._save(action)
        self._audit("EXECUTED", action, actor, result=result)
        return action

    # ---------- audit ----------
    def verify_audit(self) -> dict:
        """Recompute the hash chain. Any edited, removed or reordered line breaks it."""
        prev, n = GENESIS, 0
        if not self.audit_path.exists():
            return {"ok": True, "entries": 0}
        with self.audit_path.open(encoding="utf-8") as fh:
            for n, line in enumerate((l for l in fh if l.strip()), 1):
                entry = json.loads(line)
                claimed = entry.pop("entry_hash", "")
                if entry.get("prev") != prev:
                    return {"ok": False, "entries": n, "broken_at_line": n, "reason": "PREV_HASH_MISMATCH"}
                real = hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                if real != claimed:
                    return {"ok": False, "entries": n, "broken_at_line": n, "reason": "ENTRY_MODIFIED"}
                prev = claimed
        return {"ok": True, "entries": n}
