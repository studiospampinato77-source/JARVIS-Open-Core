import json
import tempfile
import unittest
from email import message_from_bytes
from pathlib import Path

import _paths  # noqa: F401
from jarvis_action_gate_v1 import ActionGate, GateError

EMAIL = {"to": "editor@example.org", "subject": "Book proposal", "body": "Hello"}


class ActionGateTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.gate = ActionGate(self.root)

    def refused(self, code, fn, *a, **kw):
        with self.assertRaises(GateError) as ctx:
            fn(*a, **kw)
        self.assertEqual(ctx.exception.code, code)

    def test_pending_action_never_executes(self):
        a = self.gate.prepare("email", EMAIL)
        self.assertEqual(a["status"], "PENDING_APPROVAL")
        self.refused("NOT_APPROVED", self.gate.execute, a["id"])
        self.assertFalse((self.root / "outbox").exists())

    def test_approved_email_goes_to_local_outbox(self):
        a = self.gate.prepare("email", EMAIL)
        self.gate.approve(a["id"], "owner")
        done = self.gate.execute(a["id"])
        self.assertEqual(done["status"], "EXECUTED")
        msg = message_from_bytes(Path(done["result"]["file"]).read_bytes())
        self.assertEqual(msg["To"], EMAIL["to"])
        self.assertEqual(msg["X-Action-Hash"], a["hash"])

    def test_content_changed_after_approval_is_refused(self):
        a = self.gate.prepare("email", EMAIL)
        self.gate.approve(a["id"], "owner")
        p = self.root / "actions" / f"{a['id']}.json"
        stored = json.loads(p.read_text())
        stored["payload"]["body"] = "Hello, buy now!"
        p.write_text(json.dumps(stored))
        self.refused("CONTENT_CHANGED_AFTER_APPROVAL", self.gate.execute, a["id"])

    def test_never_executes_twice(self):
        a = self.gate.prepare("email", EMAIL)
        self.gate.approve(a["id"], "owner")
        self.gate.execute(a["id"])
        self.refused("ALREADY_EXECUTED", self.gate.execute, a["id"])

    def test_daily_limit(self):
        gate = ActionGate(self.root, daily_limits={"email": 2})
        ids = []
        for i in range(3):
            a = gate.prepare("email", dict(EMAIL, to=f"r{i}@example.org"))
            gate.approve(a["id"], "owner")
            ids.append(a["id"])
        gate.execute(ids[0])
        gate.execute(ids[1])
        self.refused("DAILY_LIMIT_REACHED", gate.execute, ids[2])

    def test_payments_are_disabled_by_default(self):
        a = self.gate.prepare("payment", {"to": "shop@example.org", "amount_eur": 10})
        self.gate.approve(a["id"], "owner")
        self.refused("DAILY_LIMIT_REACHED", self.gate.execute, a["id"])

    def test_opt_out_blocks_prepare_and_execute(self):
        a = self.gate.prepare("email", EMAIL)
        self.gate.approve(a["id"], "owner")
        self.gate.opt_out("Editor@Example.org")
        self.refused("RECIPIENT_OPTED_OUT", self.gate.execute, a["id"])
        self.refused("RECIPIENT_OPTED_OUT", self.gate.prepare, "email", EMAIL)

    def test_kill_switch(self):
        a = self.gate.prepare("email", EMAIL)
        self.gate.approve(a["id"], "owner")
        (self.root / "STOP").touch()
        self.refused("KILL_SWITCH_ON", self.gate.execute, a["id"])

    def test_rejected_and_unknown(self):
        a = self.gate.prepare("email", EMAIL)
        self.gate.reject(a["id"], "owner", "tone too pushy")
        self.refused("NOT_APPROVED", self.gate.execute, a["id"])
        self.refused("NOT_PENDING", self.gate.approve, a["id"], "owner")
        self.refused("UNKNOWN_KIND", self.gate.prepare, "wire_transfer", {})
        self.refused("APPROVER_REQUIRED", self.gate.approve, a["id"], " ")
        self.refused("BAD_ACTION_ID", self.gate.get, "../secrets")

    def test_audit_chain_detects_tampering(self):
        a = self.gate.prepare("email", EMAIL)
        self.gate.approve(a["id"], "owner")
        self.gate.execute(a["id"])
        self.assertEqual(self.gate.verify_audit(), {"ok": True, "entries": 3})
        lines = self.gate.audit_path.read_text().splitlines()
        lines[1] = lines[1].replace('"owner"', '"someone_else"')
        self.gate.audit_path.write_text("\n".join(lines) + "\n")
        bad = self.gate.verify_audit()
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["broken_at_line"], 2)

    def test_deleted_audit_line_is_detected(self):
        a = self.gate.prepare("email", EMAIL)
        self.gate.approve(a["id"], "owner")
        lines = self.gate.audit_path.read_text().splitlines()
        self.gate.audit_path.write_text(lines[1] + "\n")
        self.assertFalse(self.gate.verify_audit()["ok"])


if __name__ == "__main__":
    unittest.main()
