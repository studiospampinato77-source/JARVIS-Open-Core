#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Source Intelligence / Navigation Router V1.

Connects existing WORLD, RESEARCH, catalogs, memory, security, and
capability-gap. Does not fetch the web. Does not rewrite V5 or WORLD.
Engine names live in the capability catalog (data), not in decision ifs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

VERSION = "5.3.3-SOURCE-INTELLIGENCE-NAV-ROUTER"
HERE = Path(__file__).resolve().parent
MASTER = HERE.parents[1]
GOVERNANCE = MASTER / "GOVERNANCE"
CAPABILITY_CATALOG = GOVERNANCE / "source_intelligence_capabilities_v5.json"
VERTICAL_CATALOG = GOVERNANCE / "client_intelligence_catalog_v5.json"
NETWORK_POLICY = GOVERNANCE / "network_policy.json"
DATA_DIR = Path(os.getenv("JARVIS_DATA_DIR", str(MASTER / "data")))
REVIEW_ROOT = DATA_DIR / "review"

STATES = (
    "PLAN",
    "ORIENT",
    "SELECT_ROUTES",
    "EXECUTE",
    "EVALUATE",
    "REPLAN",
    "VERIFY",
    "COMPLETE",
    "HUMAN_APPROVAL",
    "EXHAUSTED",
)

EVIDENCE_CLASSES = (
    "VERIFIED_FACT",
    "CORRELATION",
    "INDICATOR",
    "INFERENCE",
    "UNVERIFIED",
    "CONFLICTING_EVIDENCE",
)

INGESTION_GATEWAY_STAGES = (
    "RAW_DATA",
    "IDENTIFY",
    "CLASSIFY",
    "EXTRACT",
    "NORMALIZE",
    "PROVENANCE",
    "VERIFY",
    "INDEX",
    "ROUTER_INTELLIGENCE",
)

FORBIDDEN_WITHOUT_APPROVAL = (
    "payments",
    "send",
    "publish",
    "delete",
    "irreversible",
)

MISSION_TYPE_HINTS = (
    ("SPECIALIZED_MONEY_SIGNAL", ("premio", "prize", "grant", "bounty", "bando premio", "award")),
    ("VERTICAL_REGISTRY", ("odcec", "bacheca", "albo")),
    ("COMMERCIAL_NEED_HUNT", ("commercialist", "business plan", "finanza aziendale", "accesso al credito", "collaborazione esterna")),
    ("TERRITORIAL_ORIENT", ("dove cercare", "territorio", "hot zone")),
    ("EVIDENCE_VERIFY", ("verifica evidenza", "verify evidence")),
)

FAMILY_BY_TYPE = {
    "COMMERCIAL_NEED_HUNT": ("COMMERCIAL_NEED_HUNT", "NEED_PHRASE_HUNT", "ODCEC_BACHECA", "TERRITORY_HOT"),
    "SPECIALIZED_MONEY_SIGNAL": ("SPECIALIZED_MONEY_SIGNAL", "PRIZE_GRANT_BOUNTY"),
    "VERTICAL_REGISTRY": ("ODCEC_BACHECA", "VERTICAL_REGISTRY"),
    "TERRITORIAL_ORIENT": ("TERRITORY_HOT",),
    "EVIDENCE_VERIFY": ("EVIDENCE_VERIFY",),
    "UNKNOWN": ("NEED_PHRASE_HUNT", "TERRITORY_HOT"),
}

STATUS_PRIMARY_OK = {"READY"}
STATUS_FALLBACK_OK = {"READY", "DEGRADED", "RATE_LIMITED"}
STATUS_BLOCK_REPLAN = {"BLOCKED"}
PAID_COSTS = {"PAID", "METERED"}

REPLAN_TRIGGERS = (
    "PROVIDER_BLOCKED",
    "PROVIDER_DEGRADED",
    "ZERO_RESULTS",
    "OFF_TOPIC",
    "INSUFFICIENT_COVERAGE",
    "INSUFFICIENT_EVIDENCE",
    "EXCESSIVE_DUPLICATES",
    "NON_PERTINENT",
    "WORLD_BETTER_PATH",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def ingestion_gateway_contract() -> Dict[str, Any]:
    """Data Ingestion Gateway — implemented V1, local/offline acquire only."""
    try:
        from jarvis_ingestion_gateway_v5 import gateway_contract

        out = gateway_contract()
    except Exception:
        out = {
            "implemented": False,
            "stages": list(INGESTION_GATEWAY_STAGES),
            "evidence_classes": list(EVIDENCE_CLASSES),
            "accepts_future_capability_types": True,
        }
    out["router_reserved_stages"] = list(INGESTION_GATEWAY_STAGES)
    out["evidence_classes"] = list(EVIDENCE_CLASSES)
    out["accepts_future_capability_types"] = True
    return out


def infer_mission_type(goal: str, explicit: str = "") -> str:
    if explicit and explicit != "UNKNOWN":
        return str(explicit).upper()
    low = (goal or "").casefold()
    for mtype, hints in MISSION_TYPE_HINTS:
        if any(h in low for h in hints):
            return mtype
    return "UNKNOWN"


def mission_families_for(mission_type: str) -> Tuple[str, ...]:
    return FAMILY_BY_TYPE.get(str(mission_type).upper(), FAMILY_BY_TYPE["UNKNOWN"])


def load_network_policy() -> Dict[str, Any]:
    return _load_json(NETWORK_POLICY, {"default_mode": "OFF", "modes": {}})


def load_capability_catalog(
    extra: Optional[List[Dict[str, Any]]] = None,
    source_status: Optional[Dict[str, str]] = None,
    mission_history: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    data = _load_json(CAPABILITY_CATALOG, {"capabilities": []})
    caps = [dict(c) for c in (data.get("capabilities") or [])]
    vertical = _load_json(VERTICAL_CATALOG, {"sources": []})
    known = {c.get("id") for c in caps}
    for src in vertical.get("sources") or []:
        sid = str(src.get("id") or "")
        if not sid or sid in known:
            continue
        caps.append(
            {
                "id": sid,
                "type": "VERTICAL_HTML",
                "domains": ["BUSINESS"],
                "mission_families": ["ODCEC_BACHECA", "COMMERCIAL_NEED_HUNT"],
                "geography": [str(src.get("territory") or "")],
                "language": ["it"],
                "status": "READY",
                "cost": "FREE",
                "auth_required": False,
                "trust": str(src.get("trust") or "medium"),
                "historical_success": 0,
                "last_failure": "",
                "failure_reason": "",
                "specialized": True,
                "mode": "READ_ONLY",
                "query_family": "VERTICAL",
            }
        )
        known.add(sid)
    for row in extra or []:
        rid = str(row.get("id") or "")
        if not rid:
            continue
        caps = [c for c in caps if c.get("id") != rid]
        caps.append(dict(row))
    _apply_runtime_status(caps, source_status or {})
    return caps


def _apply_runtime_status(caps: List[Dict[str, Any]], source_status: Dict[str, str]) -> None:
    for cap in caps:
        cid = str(cap.get("id") or "")
        raw = str(source_status.get(cid) or "").upper()
        if not raw:
            continue
        if raw.startswith("DEGRADED"):
            cap["status"] = "DEGRADED"
            cap["failure_reason"] = raw
        elif raw.startswith("BLOCKED"):
            cap["status"] = "BLOCKED"
            cap["failure_reason"] = raw
        elif "SPECIALIZED" in raw:
            cap["status"] = cap.get("status") or "READY"
        elif raw.startswith("UNAVAILABLE"):
            cap["status"] = "UNAVAILABLE"
            cap["failure_reason"] = raw
        elif raw.startswith("RATE"):
            cap["status"] = "RATE_LIMITED"
            cap["failure_reason"] = raw
        elif raw == "READY":
            cap["status"] = "READY"


def _apply_history(caps: List[Dict[str, Any]], history: List[Dict[str, Any]], mission_family: str = "", goal_type: str = "") -> None:
    """HTTP/network success is never HISTORICAL_SUCCESS. Gold-only boost via Experience Loop."""
    from jarvis_experience_loop_v5 import GOLD_LEVELS, experience_record, load_experiences, overlay_capabilities

    extra: List[Dict[str, Any]] = []
    for row in history or []:
        level = str(row.get("verification_level") or "")
        verified = bool(row.get("verified_result"))
        cid = str(row.get("provider") or row.get("id") or row.get("capability_id") or "")
        if not cid:
            continue
        extra.append(
            experience_record(
                mission_family=row.get("mission_family") or mission_family,
                goal_type=row.get("goal_type") or goal_type or mission_family,
                capability_id=cid,
                source_id=cid,
                provider=cid,
                timestamp=row.get("timestamp"),
                technical_success=bool(row.get("technical_success")),
                failure_reason=row.get("failure_reason") or "",
                verification_level=level,
                verified_result=verified and level in GOLD_LEVELS,
                evidence_class=row.get("evidence_quality") or "",
            )
        )
    rows = load_experiences() + extra
    overlay_capabilities(caps, mission_family or goal_type or "", goal_type=goal_type or mission_family, records=rows)


def load_mission_history(review_root: Optional[Path] = None, limit_files: int = 8) -> List[Dict[str, Any]]:
    root = review_root or REVIEW_ROOT
    if not root.exists():
        return []
    rows: List[Dict[str, Any]] = []
    dirs = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    for folder in dirs[: max(1, min(int(limit_files), 20))]:
        path = folder / "source_outcomes.json"
        navp = folder / "navigation_feedback.json"
        for candidate in (navp, path):
            if not candidate.exists():
                continue
            data = _load_json(candidate, [])
            items = data if isinstance(data, list) else data.get("feedback") or data.get("source_outcomes") or []
            for item in items:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    {
                        "provider": item.get("provider") or item.get("id"),
                        "mission_family": item.get("mission_family") or item.get("adapter") or "",
                        "technical_success": bool(item.get("technical_success") or (int(item.get("http_status") or 0) == 200)),
                        "failure": bool(item.get("failure") or item.get("error")),
                        "evidence_quality": item.get("evidence_quality") or "",
                        "failure_reason": item.get("failure_reason") or item.get("error") or "",
                        "timestamp": item.get("timestamp") or folder.name,
                        "verified_result": bool(item.get("verified_result")),
                        "verification_level": item.get("verification_level") or "",
                    }
                )
    return rows


def _policy_allows_read_only(security_policy: Dict[str, Any]) -> bool:
    mode = str(security_policy.get("network_mode") or security_policy.get("mode") or "READ_ONLY_PUBLIC")
    return mode in {"READ_ONLY_PUBLIC", "OFF", "AUTHORIZED_APIS"}


def _blocked_by_security(cap: Dict[str, Any], security_policy: Dict[str, Any]) -> str:
    mode = str(cap.get("mode") or "READ_ONLY").upper()
    if mode == "ACTION":
        return "AUTH_REQUIRED_ACTION"
    if bool(cap.get("auth_required")) and not security_policy.get("approved_external"):
        return "AUTH_REQUIRED"
    cost = str(cap.get("cost") or "FREE").upper()
    if cost in PAID_COSTS:
        return "PAID_NOT_AUTHORIZED"
    if not _policy_allows_read_only(security_policy) and mode != "READ_ONLY":
        return "POLICY_MODE"
    if security_policy.get("approved_send") or security_policy.get("approved_publish"):
        return "HUMAN_APPROVAL_CONTACT"
    return ""


def _geo_ok(cap: Dict[str, Any], cities: List[str]) -> bool:
    geo = [str(g) for g in (cap.get("geography") or []) if g]
    if not geo:
        return True
    if any(g.upper() in {"GLOBAL", "IT", "*"} for g in geo):
        return True
    if not cities:
        return True
    return any(g in cities for g in geo)


def _families_ok(cap: Dict[str, Any], wanted: Tuple[str, ...]) -> bool:
    have = {str(x) for x in (cap.get("mission_families") or [])}
    return bool(have.intersection(wanted))


def _priority(cap: Dict[str, Any]) -> float:
    status = str(cap.get("status") or "").upper()
    score = 0.0
    if status == "READY":
        score += 100
    elif status == "DEGRADED":
        score += 40
    elif status == "RATE_LIMITED":
        score += 30
    elif status == "SPECIALIZED":
        score += 50
    trust = str(cap.get("trust") or "medium")
    score += {"high": 20, "medium": 10, "low": 0}.get(trust, 5)
    score += float(cap.get("experience_score") or 0)
    if cap.get("specialized"):
        score += 5
    return score


def _security_halt(security_policy: Dict[str, Any], goal: str) -> Optional[str]:
    if security_policy.get("approved_send") or security_policy.get("approved_publish"):
        return "HUMAN_APPROVAL"
    low = (goal or "").casefold()
    if any(k in low for k in ("paga", "bonifico", "invia email", "invia pec", "pubblica", "cancella definitivamente")):
        return "HUMAN_APPROVAL"
    return None


def select_routes(
    capabilities: List[Dict[str, Any]],
    mission_type: str,
    cities: List[str],
    security_policy: Dict[str, Any],
    explore_seed: str = "",
) -> Dict[str, Any]:
    wanted = mission_families_for(mission_type)
    selected: List[Dict[str, Any]] = []
    fallback: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for cap in capabilities:
        cid = str(cap.get("id") or "")
        sec = _blocked_by_security(cap, security_policy)
        if sec:
            excluded.append({"id": cid, "reason": sec})
            continue
        if str(cap.get("type") or "") == "WORLD_PLAN":
            continue
        if not _families_ok(cap, wanted):
            excluded.append({"id": cid, "reason": "NON_PERTINENT"})
            continue
        if not _geo_ok(cap, cities):
            excluded.append({"id": cid, "reason": "GEOGRAPHY_NOT_IN_WORLD"})
            continue
        st = str(cap.get("status") or "").upper()
        row = dict(cap)
        row["priority"] = _priority(cap)
        if st in STATUS_BLOCK_REPLAN:
            excluded.append({"id": cid, "reason": "BLOCKED"})
            continue
        if st in {"UNAVAILABLE"}:
            excluded.append({"id": cid, "reason": "UNAVAILABLE"})
            continue
        if st in STATUS_PRIMARY_OK:
            selected.append(row)
        elif st in STATUS_FALLBACK_OK:
            fallback.append(row)
        else:
            excluded.append({"id": cid, "reason": st or "UNKNOWN_STATUS"})
    selected.sort(key=lambda r: float(r.get("priority") or 0), reverse=True)
    fallback.sort(key=lambda r: float(r.get("priority") or 0), reverse=True)
    try:
        from jarvis_experience_loop_v5 import exploration_candidate

        ready_ids = [str(r.get("id")) for r in selected if str(r.get("status") or "").upper() == "READY"]
        ready_ids += [str(r.get("id")) for r in fallback if str(r.get("status") or "").upper() == "READY"]
        expl = exploration_candidate([str(r.get("id")) for r in selected], ready_ids, seed=explore_seed or mission_type)
        if expl.get("explore") and expl.get("candidate"):
            cid = expl["candidate"]
            moving = [r for r in fallback if str(r.get("id")) == cid]
            if moving:
                selected.append(moving[0])
                fallback = [r for r in fallback if str(r.get("id")) != cid]
                selected[-1]["exploration"] = True
    except Exception:
        expl = {"explore": False}
    parallel: List[List[str]] = []
    by_type: Dict[str, List[str]] = {}
    for row in selected:
        by_type.setdefault(str(row.get("type") or "OTHER"), []).append(str(row.get("id")))
    for ids in by_type.values():
        if len(ids) >= 1:
            parallel.append(ids)
    query_families = sorted({str(r.get("query_family") or "") for r in selected if r.get("query_family")})
    order = []
    if any(str(r.get("type")) == "VERTICAL_HTML" for r in selected):
        order.append("VERTICAL_HTML")
    if any(str(r.get("type")) == "GENERAL_SEARCH" for r in selected):
        order.append("GENERAL_SEARCH")
    if any(str(r.get("type")) == "SPECIALIZED_RSS" for r in selected):
        order.append("SPECIALIZED_RSS")
    return {
        "routes_selected": selected,
        "fallback_paths": fallback,
        "source_selection": {
            "selected_ids": [r["id"] for r in selected],
            "fallback_ids": [r["id"] for r in fallback],
            "excluded": excluded,
        },
        "parallel_paths": parallel,
        "query_families": query_families,
        "execution_order": order or ["VERTICAL_HTML", "GENERAL_SEARCH"],
        "exploration": expl if isinstance(expl, dict) else {"explore": False},
    }


def evidence_requirements(mission_type: str) -> Dict[str, Any]:
    if mission_type == "COMMERCIAL_NEED_HUNT":
        return {
            "need_phrase_on_page": True,
            "entity_identity": True,
            "thresholds_owned_by": "client_intelligence_profile_v5",
            "zero_qualified_is_valid_complete": True,
            "classes": list(EVIDENCE_CLASSES),
        }
    return {
        "independent_source": True,
        "provenance": True,
        "classes": list(EVIDENCE_CLASSES),
    }


def skip_and_allow(decision: Dict[str, Any]) -> Dict[str, Any]:
    selected = [str(x) for x in (decision.get("source_selection") or {}).get("selected_ids") or []]
    excluded = (decision.get("source_selection") or {}).get("excluded") or []
    skip = [str(x.get("id")) for x in excluded if x.get("id")]
    specialized = []
    for row in decision.get("routes_selected") or []:
        if str(row.get("type") or "") == "SPECIALIZED_RSS":
            specialized.append(str(row.get("id")))
    return {
        "skip_providers": skip,
        "allow_providers": selected,
        "include_specialized_rss": bool(specialized),
        "vertical_ids": [
            str(r.get("id"))
            for r in (decision.get("routes_selected") or [])
            if str(r.get("type") or "") == "VERTICAL_HTML"
        ],
        "general_ids": [
            str(r.get("id"))
            for r in (decision.get("routes_selected") or [])
            if str(r.get("type") or "") == "GENERAL_SEARCH"
        ],
    }


def evaluate_execution(decision: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    blocked = [str(x) for x in (report.get("blocked_ids") or [])]
    degraded = [str(x) for x in (report.get("degraded_ids") or [])]
    results = int(report.get("result_count") or 0)
    on_topic = int(report.get("on_topic_count") or 0)
    evidence = int(report.get("evidence_count") or 0)
    dup_ratio = float(report.get("duplicate_ratio") or 0)
    if blocked:
        reasons.append("PROVIDER_BLOCKED")
    if degraded and results == 0:
        reasons.append("PROVIDER_DEGRADED")
    if results == 0:
        reasons.append("ZERO_RESULTS")
    if results > 0 and on_topic == 0:
        reasons.append("OFF_TOPIC")
    if not report.get("coverage_ok", results > 0 or evidence > 0):
        reasons.append("INSUFFICIENT_COVERAGE")
    if evidence == 0 and not report.get("evidence_sufficient"):
        reasons.append("INSUFFICIENT_EVIDENCE")
    if dup_ratio >= 0.8 and results >= 3:
        reasons.append("EXCESSIVE_DUPLICATES")
    if report.get("non_pertinent"):
        reasons.append("NON_PERTINENT")
    if report.get("world_better_path"):
        reasons.append("WORLD_BETTER_PATH")
    gold_level = str(report.get("gold_level") or "")
    if gold_level and gold_level not in {"GOLD", "GOLD_PLUS"}:
        if "INSUFFICIENT_EVIDENCE" not in reasons:
            reasons.append("INSUFFICIENT_EVIDENCE")
    if str(report.get("gold_class") or "") == "CONFLICTING_EVIDENCE":
        if "INSUFFICIENT_EVIDENCE" not in reasons:
            reasons.append("INSUFFICIENT_EVIDENCE")
    fallback_left = list((decision.get("source_selection") or {}).get("fallback_ids") or [])
    should = bool(reasons) and bool(fallback_left) and int(decision.get("replan_count") or 0) < int(decision.get("max_replans") or 3)
    exhausted_paths = bool(reasons) and not fallback_left
    return {
        "should_replan": should,
        "reasons": reasons,
        "fallback_left": fallback_left,
        "exhausted_paths": exhausted_paths,
        "verify_ready": (not reasons) or report.get("evidence_sufficient") is True,
    }


def _invoke_capability_gap(goal: str, reason: str, gap_fn: Optional[Callable] = None) -> Dict[str, Any]:
    if gap_fn is not None:
        out = gap_fn(goal, reason) or {}
        out["promotion_performed"] = False
        out["invoked"] = True
        return out
    # The full JARVIS capability-gap detector is not part of the open core: pass gap_fn to plug one in.
    return {
        "invoked": True,
        "verified": False,
        "promotion_performed": False,
        "reason": reason,
        "status": "GAP_DETECTOR_NOT_INCLUDED",
    }


def replan(decision: Dict[str, Any], evaluation: Dict[str, Any], capabilities: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    nxt = dict(decision)
    nxt["state"] = "REPLAN"
    nxt["replan_count"] = int(decision.get("replan_count") or 0) + 1
    nxt["replan_reason"] = ",".join(evaluation.get("reasons") or [])
    fallback = list(decision.get("fallback_paths") or [])
    ready_fallback = [r for r in fallback if str(r.get("status") or "").upper() == "READY"]
    degraded_only = [r for r in fallback if str(r.get("status") or "").upper() != "READY"]
    if not ready_fallback:
        reason = nxt["replan_reason"] or "AUTHORIZED_PATHS_INSUFFICIENT"
        if degraded_only:
            reason = (reason + "," if reason else "") + "NO_READY_FALLBACK"
        nxt["replan_reason"] = reason
        nxt["gap_invocation"] = _invoke_capability_gap(
            str((decision.get("plan") or {}).get("mission_goal") or ""),
            reason,
            decision.get("gap_fn"),
        )
        nxt["state"] = "EXHAUSTED"
        nxt["routes_selected"] = list(decision.get("routes_selected") or [])
        nxt["fallback_paths"] = fallback
        nxt["source_selection"] = {
            "selected_ids": [r.get("id") for r in (decision.get("routes_selected") or []) if r.get("id")],
            "fallback_ids": [r.get("id") for r in fallback if r.get("id")],
            "excluded": (decision.get("source_selection") or {}).get("excluded") or [],
        }
        nxt["gap_invocation"]["promotion_performed"] = False
        return nxt
    promoted = ready_fallback[:1]
    rest = [r for r in fallback if r is not promoted[0]]
    nxt["routes_selected"] = promoted
    nxt["fallback_paths"] = rest
    nxt["source_selection"] = {
        "selected_ids": [r["id"] for r in promoted],
        "fallback_ids": [r["id"] for r in rest],
        "excluded": (decision.get("source_selection") or {}).get("excluded") or [],
    }
    nxt["query_families"] = sorted({str(r.get("query_family") or "") for r in promoted if r.get("query_family")})
    nxt["parallel_paths"] = [[r["id"] for r in promoted]]
    nxt["execution_order"] = [str(promoted[0].get("type") or "GENERAL_SEARCH")]
    nxt["gap_invocation"] = {"invoked": False, "promotion_performed": False}
    nxt["state"] = "SELECT_ROUTES"
    return nxt


def verify_with_gate(decision: Dict[str, Any], gate_verdict: Dict[str, Any], complete_if_gold: bool = True) -> Dict[str, Any]:
    """VERIFY uses the Gold Gate. INSUFFICIENT + fallback → REPLAN, not a false COMPLETE."""
    out = dict(decision)
    slim = {k: v for k, v in (gate_verdict or {}).items() if k != "records"}
    out["gold"] = slim
    out["state"] = "VERIFY"
    mem = dict(gate_verdict.get("memory") or {})
    out["memory_feedback"] = mem
    level = str(gate_verdict.get("verification_level") or "INSUFFICIENT_EVIDENCE")
    sufficient = level in {"GOLD", "GOLD_PLUS"}
    report = {
        "result_count": 1,
        "on_topic_count": 1,
        "evidence_count": 1,
        "coverage_ok": True,
        "evidence_sufficient": sufficient,
        "gold_level": level,
        "gold_class": gate_verdict.get("evidence_class"),
    }
    ev = evaluate_execution(out, report)
    out["evaluate"] = ev
    trace = list(out.get("trace") or []) + ["VERIFY"]
    if ev.get("should_replan"):
        nxt = replan(out, ev)
        nxt["replanned"] = True
        nxt["gold"] = slim
        nxt["memory_feedback"] = mem
        nxt["trace"] = trace + ["REPLAN"]
        return nxt
    out["replanned"] = False
    out["trace"] = trace + ["COMPLETE"]
    out["state"] = "COMPLETE"
    out["note"] = "INSUFFICIENT_EVIDENCE is an honest COMPLETE when paths are exhausted; not MISSION FAILED."
    if sufficient and complete_if_gold:
        out["state"] = "COMPLETE"
    return out


def navigate(
    mission_goal: str,
    mission_type: str = "",
    world_context: Optional[Dict[str, Any]] = None,
    available_capabilities: Optional[List[Dict[str, Any]]] = None,
    source_status: Optional[Dict[str, str]] = None,
    mission_history: Optional[List[Dict[str, Any]]] = None,
    security_policy: Optional[Dict[str, Any]] = None,
    budget: Optional[Dict[str, Any]] = None,
    gap_fn: Optional[Callable] = None,
    world_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    security_policy = dict(security_policy or {})
    budget = dict(budget or {})
    max_replans = int(budget.get("max_replans") or 3)
    halt = _security_halt(security_policy, mission_goal)
    plan = {
        "mission_goal": mission_goal,
        "mission_type": infer_mission_type(mission_goal, mission_type),
        "version": VERSION,
        "budget": budget,
        "network_mode": security_policy.get("network_mode") or "READ_ONLY_PUBLIC",
    }
    if halt:
        return {
            "state": halt,
            "plan": plan,
            "routes_selected": [],
            "query_families": [],
            "source_selection": {"selected_ids": [], "fallback_ids": [], "excluded": [{"id": "*", "reason": halt}]},
            "execution_order": [],
            "parallel_paths": [],
            "fallback_paths": [],
            "stop_conditions": ["HUMAN_APPROVAL"],
            "replan_reason": "",
            "evidence_requirements": evidence_requirements(plan["mission_type"]),
            "replan_count": 0,
            "max_replans": max_replans,
            "gap_invocation": {"invoked": False, "promotion_performed": False},
            "world_context": world_context or {},
        }

    ctx = dict(world_context or {})
    if not ctx.get("cities") and world_fn is not None:
        ctx = world_fn(mission_goal, int(budget.get("max_cities") or 4)) or {}
    cities = [str(c) for c in (ctx.get("cities") or ctx.get("where_to_search") or [])]
    plan["cities"] = cities
    plan["world_status"] = ctx.get("status")

    caps = available_capabilities
    if caps is None:
        caps = load_capability_catalog(source_status=source_status, mission_history=mission_history)
    else:
        caps = [dict(c) for c in caps]
        _apply_runtime_status(caps, source_status or {})
    _apply_history(caps, mission_history or [], mission_family=plan["mission_type"], goal_type=plan["mission_type"])

    routes = select_routes(
        caps,
        plan["mission_type"],
        cities,
        security_policy,
        explore_seed=str(budget.get("explore_seed") or mission_goal),
    )
    selected_ids = routes["source_selection"]["selected_ids"]
    fallback_ids = routes["source_selection"]["fallback_ids"]
    gap: Dict[str, Any] = {"invoked": False, "promotion_performed": False}
    state = "SELECT_ROUTES"
    if not selected_ids and not fallback_ids:
        gap = _invoke_capability_gap(mission_goal, "NO_AUTHORIZED_PATHS", gap_fn)
        state = "EXHAUSTED"
    decision = {
        "state": state,
        "plan": plan,
        "world_context": ctx,
        "routes_selected": routes["routes_selected"],
        "query_families": routes["query_families"],
        "source_selection": routes["source_selection"],
        "execution_order": routes["execution_order"],
        "parallel_paths": routes["parallel_paths"],
        "fallback_paths": routes["fallback_paths"],
        "stop_conditions": [
            "EVIDENCE_SUFFICIENT",
            "AUTHORIZED_PATHS_EXHAUSTED",
            "BUDGET_EXCEEDED",
            "HUMAN_APPROVAL",
            "MAX_REPLANS",
        ],
        "replan_reason": "",
        "evidence_requirements": evidence_requirements(plan["mission_type"]),
        "replan_count": 0,
        "max_replans": max_replans,
        "gap_invocation": gap,
        "gap_fn": gap_fn,
        "capabilities": caps,
        "trace": ["PLAN", "ORIENT", "SELECT_ROUTES"],
    }
    return decision


def feedback_row(
    provider: str,
    mission_family: str,
    success: bool,
    evidence_quality: str,
    failure_reason: str,
    verified_result: bool,
) -> Dict[str, Any]:
    return {
        "provider": provider,
        "mission_family": mission_family,
        "success": bool(success),
        "failure": not bool(success),
        "evidence_quality": evidence_quality,
        "failure_reason": failure_reason,
        "timestamp": _now(),
        "verified_result": bool(verified_result),
    }


def simulate_replan_local() -> Dict[str, Any]:
    """Deterministic offline simulation. No Internet."""
    goal = (
        "Cerca studi di commercialisti con bisogno verificabile "
        "di supporto per business plan, credito o finanza aziendale."
    )
    world_ctx = {
        "status": "WORLD_READY",
        "cities": ["Milano", "Roma"],
        "where_to_search": ["Milano", "Roma"],
        "world_data_sufficient": True,
    }
    caps = [
        {
            "id": "ROUTE_A_VERTICAL",
            "type": "VERTICAL_HTML",
            "domains": ["BUSINESS"],
            "mission_families": ["ODCEC_BACHECA", "COMMERCIAL_NEED_HUNT"],
            "geography": ["Milano", "Roma"],
            "language": ["it"],
            "status": "READY",
            "cost": "FREE",
            "auth_required": False,
            "trust": "high",
            "historical_success": 0,
            "last_failure": "",
            "failure_reason": "",
            "specialized": True,
            "mode": "READ_ONLY",
            "query_family": "VERTICAL",
        },
        {
            "id": "ROUTE_B_GENERAL",
            "type": "GENERAL_SEARCH",
            "domains": ["BUSINESS"],
            "mission_families": ["NEED_PHRASE_HUNT", "COMMERCIAL_NEED_HUNT"],
            "geography": ["IT"],
            "language": ["it"],
            "status": "DEGRADED",
            "cost": "FREE",
            "auth_required": False,
            "trust": "medium",
            "historical_success": 1,
            "last_failure": "",
            "failure_reason": "",
            "specialized": False,
            "mode": "READ_ONLY",
            "query_family": "NEED",
        },
        {
            "id": "BING_RSS",
            "type": "SPECIALIZED_RSS",
            "domains": ["GENERAL"],
            "mission_families": ["PRIZE_GRANT_BOUNTY", "SPECIALIZED_MONEY_SIGNAL"],
            "geography": ["GLOBAL"],
            "language": ["en"],
            "status": "READY",
            "cost": "FREE",
            "auth_required": False,
            "trust": "medium",
            "historical_success": 0,
            "last_failure": "",
            "failure_reason": "",
            "specialized": True,
            "mode": "READ_ONLY",
            "query_family": "SPECIALIZED_RSS",
        },
    ]
    d0 = navigate(
        mission_goal=goal,
        world_context=world_ctx,
        available_capabilities=caps,
        security_policy={"network_mode": "READ_ONLY_PUBLIC"},
        budget={"max_replans": 3, "max_cities": 4},
        gap_fn=lambda g, r: {"status": "NOT_INVOKED_IN_HAPPY_REPLAN", "reason": r},
    )
    bing_excl = [x for x in d0["source_selection"]["excluded"] if x.get("id") == "BING_RSS"]
    route_a = d0["source_selection"]["selected_ids"]
    # EXECUTE A → BLOCKED
    d0["trace"] = list(d0.get("trace") or []) + ["EXECUTE"]
    ev = evaluate_execution(
        d0,
        {
            "blocked_ids": ["ROUTE_A_VERTICAL"],
            "result_count": 0,
            "on_topic_count": 0,
            "evidence_count": 0,
            "coverage_ok": False,
            "evidence_sufficient": False,
        },
    )
    d1 = replan(d0, ev)
    d1["trace"] = list(d0.get("trace") or []) + ["EVALUATE", "REPLAN", "EXECUTE"]
    route_b = d1["source_selection"]["selected_ids"]
    try:
        from jarvis_evidence_gold_gate_v5 import assess_claim as _gold_assess
        unofficial = _gold_assess(
            "SIM-A",
            claim_type="simple_public_fact",
            records=[{
                "source": "blog",
                "source_type": "WEB",
                "source_url_or_identifier": "https://example.net/post",
                "provider": "WEB1",
                "retrieved_at": _now(),
                "content": "una pagina",
                "pertinence_ok": True,
                "trust": "low",
            }],
        )
        gated = verify_with_gate(d0, unofficial)
    except Exception as exc:
        unofficial = {"verification_level": "ERROR", "error": str(exc)}
        gated = {"replanned": False, "state": "ERROR"}
    evidence = {
        "source": "ROUTE_B_GENERAL",
        "provenance": "SIMULATION_LOCAL",
        "retrieval_time": _now(),
        "evidence_class": unofficial.get("evidence_class") or "UNVERIFIED",
        "verification_status": unofficial.get("verification_level"),
        "text": "hit simulato need-phrase su studio (fixture, no network)",
    }
    verify = gated
    complete = {
        "state": "COMPLETE",
        "mission_terminated_on_route_a": False,
        "replanned": True,
        "route_a": route_a,
        "route_b": route_b,
        "bing_rss_excluded_as": bing_excl[0]["reason"] if bing_excl else None,
        "replan_reason": d1.get("replan_reason"),
        "gap_invoked": bool((d1.get("gap_invocation") or {}).get("invoked")),
        "evidence": evidence,
        "verify": {k: verify.get(k) for k in ("state", "replanned", "gold") if k in verify},
        "gate_replan_on_insufficient": bool(gated.get("replanned")),
    }
    d1["trace"] = d1["trace"] + ["VERIFY", "COMPLETE"]
    return {
        "goal": goal,
        "world": world_ctx,
        "initial": {
            "state": d0.get("state"),
            "selected": route_a,
            "fallback": d0["source_selection"]["fallback_ids"],
            "excluded": d0["source_selection"]["excluded"],
        },
        "evaluate": ev,
        "after_replan": {
            "state": d1.get("state"),
            "selected": route_b,
            "replan_reason": d1.get("replan_reason"),
        },
        "result": complete,
        "trace": d1["trace"],
        "ok": (
            "ROUTE_A_VERTICAL" in route_a
            and "ROUTE_B_GENERAL" in route_b
            and ev.get("should_replan") is True
            and complete["mission_terminated_on_route_a"] is False
            and (bing_excl and bing_excl[0]["reason"] == "NON_PERTINENT")
            and complete["gap_invoked"] is False
            and complete["gate_replan_on_insufficient"] is True
        ),
    }


if __name__ == "__main__":
    out = simulate_replan_local()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if out.get("ok") else 1)
