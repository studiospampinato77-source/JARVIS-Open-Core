#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JARVIS Experience / Learning Loop V1.

Learns only from Gold-verified outcomes. HTTP 200 is TECHNICAL_SUCCESS only.
Does not assign GOLD. Does not install/promote code.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION = "5.3.2-EXPERIENCE-LOOP"
HERE = Path(__file__).resolve().parent
MASTER = HERE.parents[1]
POLICY_PATH = MASTER / "GOVERNANCE" / "experience_loop_policy_v5.json"
DATA_DIR = Path(os.getenv("JARVIS_DATA_DIR", str(MASTER / "data")))
EXPERIENCE_DIR = DATA_DIR / "experience"
EXPERIENCE_LOG = EXPERIENCE_DIR / "experience.jsonl"

GOLD_LEVELS = ("GOLD", "GOLD_PLUS")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Any) -> str:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt or "")


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def load_policy() -> Dict[str, Any]:
    if POLICY_PATH.exists():
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    return {
        "silver_boost": 0.15,
        "gold_boost": 3.0,
        "gold_plus_boost": 4.0,
        "max_positive": 12.0,
        "max_negative": 12.0,
        "half_life_days": 90,
        "recovery_days": 21,
        "recovery_penalty_factor": 0.25,
        "exploration_rate": 0.15,
        "penalty": {},
    }


def experience_record(**kwargs: Any) -> Dict[str, Any]:
    level = str(kwargs.get("verification_level") or kwargs.get("evidence_level") or "")
    verified = bool(kwargs.get("verified_result"))
    gold = level == "GOLD" and verified
    gold_plus = level == "GOLD_PLUS" and verified
    eclass = str(kwargs.get("evidence_class") or kwargs.get("evidence_quality") or "")
    technical = bool(kwargs.get("technical_success"))
    kind = "OBSERVATION"
    if gold or gold_plus:
        kind = "VERIFIED_FACT"
    elif level or eclass:
        kind = "EXPERIENCE"
    rec = {
        "version": VERSION,
        "kind": kind,
        "mission_family": str(kwargs.get("mission_family") or ""),
        "goal_type": str(kwargs.get("goal_type") or kwargs.get("mission_family") or ""),
        "capability_id": str(kwargs.get("capability_id") or kwargs.get("source_id") or kwargs.get("provider") or ""),
        "source_id": str(kwargs.get("source_id") or kwargs.get("capability_id") or ""),
        "provider": str(kwargs.get("provider") or ""),
        "route_id": str(kwargs.get("route_id") or ""),
        "query_family": str(kwargs.get("query_family") or ""),
        "timestamp": _iso(kwargs.get("timestamp") or _now()),
        "technical_success": technical,
        "failure_reason": str(kwargs.get("failure_reason") or ""),
        "failure_class": str(kwargs.get("failure_class") or _classify_failure(kwargs.get("failure_reason") or "")),
        "evidence_level": str(kwargs.get("evidence_level") or level),
        "verification_level": level,
        "verified_result": verified,
        "gold_result": gold,
        "gold_plus_result": gold_plus,
        "insufficient_evidence": level == "INSUFFICIENT_EVIDENCE" or eclass == "UNVERIFIED" and not verified,
        "conflicting_evidence": eclass == "CONFLICTING_EVIDENCE" or "CONFLICTING" in str(kwargs.get("failure_reason") or "").upper(),
        "replan_used": bool(kwargs.get("replan_used")),
        "replan_success": bool(kwargs.get("replan_success")),
        "elapsed_time": kwargs.get("elapsed_time") if kwargs.get("elapsed_time") is not None else None,
        "cost_if_known": kwargs.get("cost_if_known") if kwargs.get("cost_if_known") is not None else None,
        "duplicate_signal": bool(kwargs.get("duplicate_signal")),
        "relevance": kwargs.get("relevance") if kwargs.get("relevance") is not None else None,
        "human_outcome_if_available": kwargs.get("human_outcome_if_available") or "",
        "positive_boost_eligible": bool((gold or gold_plus) and verified),
    }
    rec["insufficient_evidence"] = bool(
        rec["insufficient_evidence"] or level == "INSUFFICIENT_EVIDENCE"
    )
    return rec


def _classify_failure(reason: str) -> str:
    u = str(reason or "").upper()
    mapping = (
        ("CAPTCHA", "CAPTCHA"),
        ("BLOCKED", "BLOCKED"),
        ("TIMEOUT", "TIMEOUT"),
        ("STALE", "STALE"),
        ("CONFLICT", "CONFLICTING_EVIDENCE"),
        ("NON_PERTINENT", "NON_PERTINENT"),
        ("ZERO", "ZERO_RESULT"),
        ("INSUFFICIENT", "INSUFFICIENT_EVIDENCE"),
        ("CONNECTION", "TECHNICAL_FAILURE"),
        ("RESET", "TECHNICAL_FAILURE"),
        ("HTTP", "TECHNICAL_FAILURE"),
    )
    for needle, label in mapping:
        if needle in u:
            return label
    if u:
        return "TECHNICAL_FAILURE"
    return ""


def append_experience(rec: Dict[str, Any], path: Optional[Path] = None) -> Path:
    dest = path or EXPERIENCE_LOG
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    return dest


def load_experiences(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    dest = path or EXPERIENCE_LOG
    if not dest.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in dest.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _decay(age_days: float, half_life: float) -> float:
    if half_life <= 0:
        return 1.0
    return 0.5 ** (max(0.0, age_days) / float(half_life))


def _context_key(mission_family: str, capability_id: str, goal_type: str = "") -> Tuple[str, str, str]:
    return (str(mission_family or "").upper(), str(capability_id or "").upper(), str(goal_type or mission_family or "").upper())


def contextual_score(
    mission_family: str,
    capability_id: str,
    records: List[Dict[str, Any]],
    goal_type: str = "",
    now: Optional[datetime] = None,
    policy: Optional[Dict[str, Any]] = None,
    current_status: str = "",
) -> Dict[str, Any]:
    pol = policy or load_policy()
    now = now or _now()
    half = float(pol.get("half_life_days") or 90)
    recov = float(pol.get("recovery_days") or 21)
    recov_f = float(pol.get("recovery_penalty_factor") or 0.25)
    penalties = pol.get("penalty") or {}
    fam, cap, goal = _context_key(mission_family, capability_id, goal_type)
    pos = 0.0
    neg = 0.0
    last_fail: Optional[datetime] = None
    gold_n = 0
    tech_n = 0
    matched = 0
    for rec in records:
        rf, rc, rg = _context_key(rec.get("mission_family") or "", rec.get("capability_id") or rec.get("provider") or "", rec.get("goal_type") or "")
        if rf != fam or rc != cap:
            continue
        if goal and rg and rg != goal and rec.get("goal_type"):
            continue
        matched += 1
        ts = _parse_dt(rec.get("timestamp")) or now
        age = max(0.0, (now - ts).total_seconds() / 86400.0)
        w = _decay(age, half)
        if rec.get("technical_success"):
            tech_n += 1
        if rec.get("positive_boost_eligible") or (
            rec.get("verified_result") and str(rec.get("verification_level") or "") in GOLD_LEVELS
        ):
            gold_n += 1
            if rec.get("gold_plus_result"):
                pos += w * float(pol.get("gold_plus_boost") or 4.0)
            else:
                pos += w * float(pol.get("gold_boost") or 3.0)
        elif str(rec.get("verification_level") or "") == "SILVER":
            pos += w * float(pol.get("silver_boost") or 0.0)
        fail = str(rec.get("failure_class") or rec.get("failure_reason") or "")
        if rec.get("conflicting_evidence"):
            fail = "CONFLICTING_EVIDENCE"
        if fail and not rec.get("positive_boost_eligible"):
            weight = float(penalties.get(fail) or penalties.get("DEFAULT") or 0.5)
            neg += w * weight
            if last_fail is None or ts > last_fail:
                last_fail = ts
    recovered = False
    if last_fail:
        age_fail = (now - last_fail).days
        if age_fail >= recov or str(current_status).upper() == "READY":
            recovered = True
            neg *= recov_f
    pos = min(pos, float(pol.get("max_positive") or 12.0))
    neg = min(neg, float(pol.get("max_negative") or 12.0))
    explorable = True
    return {
        "mission_family": mission_family,
        "goal_type": goal_type or mission_family,
        "capability_id": capability_id,
        "score": round(pos - neg, 4),
        "positive": round(pos, 4),
        "negative": round(neg, 4),
        "gold_count": gold_n,
        "technical_success_count": tech_n,
        "matched_records": matched,
        "historical_success": gold_n,
        "recovered": recovered,
        "explorable": explorable,
        "last_failure": _iso(last_fail) if last_fail else "",
    }


def overlay_capabilities(
    capabilities: List[Dict[str, Any]],
    mission_family: str,
    goal_type: str = "",
    records: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    policy: Optional[Dict[str, Any]] = None,
    path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    rows = records if records is not None else load_experiences(path)
    for cap in capabilities:
        cid = str(cap.get("id") or "")
        stats = contextual_score(mission_family, cid, rows, goal_type=goal_type or mission_family, now=now, policy=policy, current_status=str(cap.get("status") or ""))
        cap["experience_score"] = stats["score"]
        cap["historical_success"] = int(stats["historical_success"])
        cap["_history_boost"] = stats["positive"]
        cap["_history_penalty"] = stats["negative"]
        cap["_experience"] = stats
        cap["technical_success_count"] = stats["technical_success_count"]
    return capabilities


def exploration_candidate(
    selected_ids: List[str],
    ready_pertinent_ids: List[str],
    seed: str = "",
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Deterministic exploration: never uses unseeded random."""
    pol = policy or load_policy()
    rate = float(pol.get("exploration_rate") or 0.15)
    ready = [i for i in ready_pertinent_ids if i]
    unique = list(dict.fromkeys(ready))
    if len(unique) < 2:
        return {"explore": False, "reason": "NO_ALTERNATIVE_READY", "candidate": "", "rate": rate}
    digest = hashlib.sha256((seed or "|".join(unique)).encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    alts = [i for i in unique if i not in selected_ids] or unique[1:]
    pick = alts[int(digest[8:16], 16) % len(alts)] if alts else ""
    explore = bucket < rate
    return {
        "explore": explore,
        "would_be_possible": True,
        "candidate": pick,
        "rate": rate,
        "bucket": round(bucket, 4),
        "reason": "DETERMINISTIC_SEED",
    }


def propose_capability_gap(reason: str) -> Dict[str, Any]:
    """Future Self-Evolution hook. Propose only. Never install."""
    return {
        "may_propose_gap": True,
        "may_install": False,
        "may_promote": False,
        "reason": reason,
        "note": "Experience Loop may propose a gap; SelfBuild remains approval-gated.",
    }


def run_local_tests() -> Dict[str, Any]:
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    pol = load_policy()
    recs: List[Dict[str, Any]] = []

    def chk(name: str, ok: bool, detail: Any) -> Dict[str, Any]:
        return {"id": name, "ok": bool(ok), "detail": detail}

    a = experience_record(
        mission_family="COMMERCIAL",
        capability_id="PROV_A",
        provider="PROV_A",
        timestamp=now,
        technical_success=True,
        verification_level="INSUFFICIENT_EVIDENCE",
        verified_result=False,
        failure_class="ZERO_RESULT",
        failure_reason="HTTP_200_EMPTY",
    )
    recs.append(a)
    sa = contextual_score("COMMERCIAL", "PROV_A", recs, now=now, policy=pol)
    t_a = chk("A", a["technical_success"] is True and a["positive_boost_eligible"] is False and sa["positive"] == 0, sa)

    b = experience_record(
        mission_family="COMMERCIAL",
        capability_id="PROV_B",
        provider="PROV_B",
        timestamp=now,
        technical_success=True,
        verification_level="GOLD",
        verified_result=True,
        evidence_class="VERIFIED_FACT",
    )
    recs.append(b)
    sb = contextual_score("COMMERCIAL", "PROV_B", recs, now=now, policy=pol)
    t_b = chk("B", b["positive_boost_eligible"] is True and sb["positive"] > 0 and sb["historical_success"] == 1, sb)

    c = experience_record(
        mission_family="COMMERCIAL",
        capability_id="PROV_C",
        provider="PROV_C",
        timestamp=now,
        technical_success=False,
        verification_level="INSUFFICIENT_EVIDENCE",
        verified_result=False,
        evidence_class="INFERENCE",
        failure_reason="LLM_ONLY",
    )
    recs.append(c)
    sc = contextual_score("COMMERCIAL", "PROV_C", recs, now=now, policy=pol)
    t_c = chk("C", c["positive_boost_eligible"] is False and sc["positive"] == 0, sc)

    recent = now
    old = datetime(2025, 1, 1, tzinfo=timezone.utc)
    recs.append(experience_record(
        mission_family="COMMERCIAL", capability_id="PROV_D", provider="PROV_D",
        timestamp=recent, technical_success=False, failure_class="CAPTCHA", failure_reason="CAPTCHA",
        verification_level="", verified_result=False,
    ))
    recs.append(experience_record(
        mission_family="COMMERCIAL", capability_id="PROV_E", provider="PROV_E",
        timestamp=old, technical_success=False, failure_class="CAPTCHA", failure_reason="CAPTCHA",
        verification_level="", verified_result=False,
    ))
    sd = contextual_score("COMMERCIAL", "PROV_D", recs, now=now, policy=pol)
    se = contextual_score("COMMERCIAL", "PROV_E", recs, now=now, policy=pol)
    t_d = chk("D", sd["negative"] > se["negative"], {"recent": sd["negative"], "old": se["negative"]})
    t_e = chk("E", se["negative"] < sd["negative"], {"old": se["negative"], "recent": sd["negative"]})

    recs.append(experience_record(
        mission_family="COMMERCIAL", capability_id="PROV_F", provider="PROV_F",
        timestamp=datetime(2026, 8, 1, tzinfo=timezone.utc), technical_success=False,
        failure_class="BLOCKED", failure_reason="BLOCKED", verified_result=False,
    ))
    sf = contextual_score("COMMERCIAL", "PROV_F", recs, now=now, policy=pol, current_status="READY")
    t_f = chk("F", sf["recovered"] is True and sf["explorable"] is True, sf)

    recs.append(experience_record(
        mission_family="LEGAL", capability_id="PROV_G", provider="PROV_G", timestamp=now,
        verification_level="GOLD", verified_result=True, technical_success=True,
    ))
    recs.append(experience_record(
        mission_family="COMMERCIAL", capability_id="PROV_G", provider="PROV_G", timestamp=now,
        verification_level="INSUFFICIENT_EVIDENCE", verified_result=False, technical_success=True,
        failure_class="INSUFFICIENT_EVIDENCE", failure_reason="INSUFFICIENT_EVIDENCE",
    ))
    sg_l = contextual_score("LEGAL", "PROV_G", recs, now=now, policy=pol)
    sg_c = contextual_score("COMMERCIAL", "PROV_G", recs, now=now, policy=pol)
    t_g = chk("G", sg_l["score"] > sg_c["score"], {"legal": sg_l["score"], "commercial": sg_c["score"]})

    expl = exploration_candidate(["DOM"], ["DOM", "ALT"], seed="test-h")
    t_h = chk("H", expl.get("would_be_possible") is True and "candidate" in expl, expl)

    recs.append(experience_record(
        mission_family="COMMERCIAL", capability_id="PROV_I", provider="PROV_I", timestamp=now,
        verification_level="INSUFFICIENT_EVIDENCE", verified_result=False,
        evidence_class="CONFLICTING_EVIDENCE", conflicting_evidence=True,
        failure_class="CONFLICTING_EVIDENCE", failure_reason="CONFLICTING_EVIDENCE",
        technical_success=True,
    ))
    si = contextual_score("COMMERCIAL", "PROV_I", recs, now=now, policy=pol)
    t_i = chk("I", si["positive"] == 0 and si["negative"] > 0, si)

    recs.append(experience_record(
        mission_family="COMMERCIAL", capability_id="ROUTE_FAIL", provider="ROUTE_FAIL", timestamp=now,
        technical_success=False, failure_class="BLOCKED", failure_reason="BLOCKED",
        replan_used=True, replan_success=False, verified_result=False,
    ))
    recs.append(experience_record(
        mission_family="COMMERCIAL", capability_id="ROUTE_WIN", provider="ROUTE_WIN", timestamp=now,
        technical_success=True, verification_level="GOLD", verified_result=True,
        replan_used=True, replan_success=True,
    ))
    sj_fail = contextual_score("COMMERCIAL", "ROUTE_FAIL", recs, now=now, policy=pol)
    sj_win = contextual_score("COMMERCIAL", "ROUTE_WIN", recs, now=now, policy=pol)
    t_j = chk(
        "J",
        recs[-1]["replan_success"] is True and sj_win["positive"] > 0 and sj_fail["positive"] == 0 and sj_fail["negative"] > 0,
        {"win": sj_win, "fail": sj_fail},
    )

    tests = [t_a, t_b, t_c, t_d, t_e, t_f, t_g, t_h, t_i, t_j]
    return {"version": VERSION, "ok": all(t["ok"] for t in tests), "tests": tests}


if __name__ == "__main__":
    out = run_local_tests()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if out.get("ok") else 1)
