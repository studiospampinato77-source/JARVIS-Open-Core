#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JARVIS Evidence / Gold Standard Gate V1.

Connects existing identity, qualify, hashes, and router VERIFY.
Does not fetch the web. Does not mint GOLD from LLM output.
Does not change NEED_PHRASE or commercial thresholds.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

VERSION = "5.3.2-EVIDENCE-GOLD-GATE"
HERE = Path(__file__).resolve().parent
MASTER = HERE.parents[1]
POLICY_PATH = MASTER / "GOVERNANCE" / "evidence_gold_policy_v5.json"

EVIDENCE_CLASSES = (
    "VERIFIED_FACT",
    "CORRELATION",
    "INDICATOR",
    "INFERENCE",
    "UNVERIFIED",
    "CONFLICTING_EVIDENCE",
)
LEVELS = ("RAW", "BRONZE", "SILVER", "GOLD", "GOLD_PLUS", "INSUFFICIENT_EVIDENCE")
LLM_TYPES_FALLBACK = ("LLM_SYNTHESIS", "AI_SUMMARY", "MODEL_INFERENCE")
WORLD_TYPES_FALLBACK = ("WORLD_PLAN", "WORLD_ORIENTATION")
SATELLITE_TYPES_FALLBACK = ("SATELLITE_IMAGERY", "GEO_DATASET", "WEATHER_CLIMATE", "SATELLITE")
LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_policy() -> Dict[str, Any]:
    if POLICY_PATH.exists():
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    return {"claims": {"default": {}}, "official_source_types": ["OFFICIAL", "PRIMARY", "GOVERNMENT"]}


def claim_policy(claim_type: str, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    policy = policy or _load_policy()
    claims = policy.get("claims") or {}
    base = dict(claims.get("default") or {})
    base.update(dict(claims.get(claim_type) or {}))
    base["claim_type"] = claim_type or "default"
    base["official_source_types"] = list(policy.get("official_source_types") or ["OFFICIAL", "PRIMARY", "GOVERNMENT"])
    base["official_min_trust"] = str(policy.get("official_min_trust") or "high")
    base["llm_source_types"] = list(policy.get("llm_source_types") or LLM_TYPES_FALLBACK)
    base["world_source_types"] = list(policy.get("world_source_types") or WORLD_TYPES_FALLBACK)
    base["identity_verified_tokens"] = list(policy.get("identity_verified_tokens") or ["ENTITY_VERIFIED"])
    return base


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def registrable_domain(url_or_host: str) -> str:
    raw = (url_or_host or "").strip()
    if not raw:
        return ""
    host = raw
    if "://" in raw:
        host = urlparse(raw).hostname or ""
    host = host.lower().removeprefix("www.")
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None


def evidence_record(**kwargs: Any) -> Dict[str, Any]:
    url = str(kwargs.get("source_url_or_identifier") or kwargs.get("source_url") or "")
    body = str(kwargs.get("content") or kwargs.get("text") or "")
    digest = str(kwargs.get("content_hash") or "") or (content_hash(body) if body else "")
    rec = {
        "evidence_id": str(kwargs.get("evidence_id") or ""),
        "claim_id": str(kwargs.get("claim_id") or ""),
        "source": str(kwargs.get("source") or ""),
        "source_type": str(kwargs.get("source_type") or "WEB"),
        "source_url_or_identifier": url,
        "provider": str(kwargs.get("provider") or ""),
        "retrieved_at": kwargs.get("retrieved_at") or "",
        "observed_at": kwargs.get("observed_at") or "",
        "valid_from": kwargs.get("valid_from") or "",
        "valid_to": kwargs.get("valid_to") or "",
        "content_hash": digest,
        "entity_identity": kwargs.get("entity_identity") or "",
        "identity_status": str(kwargs.get("identity_status") or ""),
        "evidence_class": str(kwargs.get("evidence_class") or "UNVERIFIED"),
        "verification_status": str(kwargs.get("verification_status") or "UNVERIFIED"),
        "independence_group": str(kwargs.get("independence_group") or ""),
        "trust": str(kwargs.get("trust") or "medium"),
        "contradictions": list(kwargs.get("contradictions") or []),
        "supporting_evidence": list(kwargs.get("supporting_evidence") or []),
        "contrary_evidence": list(kwargs.get("contrary_evidence") or []),
        "provenance": dict(kwargs.get("provenance") or {}),
        "content": body,
        "pertinence_ok": bool(kwargs.get("pertinence_ok", True)),
        "original_source": str(kwargs.get("original_source") or ""),
        "official": bool(kwargs.get("official", False)),
    }
    if not rec["evidence_id"]:
        rec["evidence_id"] = "EV-" + content_hash(url + digest + rec["provider"])[:12].upper()
    if not rec["independence_group"]:
        rec["independence_group"] = rec["original_source"] or registrable_domain(url) or rec["provider"] or rec["evidence_id"]
    rec["provenance"] = {
        "source": rec["source"],
        "source_url_or_identifier": url,
        "provider": rec["provider"],
        "retrieved_at": rec["retrieved_at"],
        "content_hash": digest,
        **rec["provenance"],
    }
    return rec


def _is_llm(rec: Dict[str, Any], pol: Dict[str, Any]) -> bool:
    return str(rec.get("source_type") or "").upper() in {x.upper() for x in (pol.get("llm_source_types") or LLM_TYPES_FALLBACK)}


def _is_world(rec: Dict[str, Any], pol: Dict[str, Any]) -> bool:
    st = str(rec.get("source_type") or "").upper()
    types = {x.upper() for x in (pol.get("world_source_types") or WORLD_TYPES_FALLBACK)}
    types.update(x.upper() for x in SATELLITE_TYPES_FALLBACK)
    return st in types


def _is_official(rec: Dict[str, Any], pol: Dict[str, Any]) -> bool:
    if rec.get("official"):
        return True
    st = str(rec.get("source_type") or "").upper()
    trust = str(rec.get("trust") or "").lower()
    types = {x.upper() for x in (pol.get("official_source_types") or [])}
    return st in types and trust == str(pol.get("official_min_trust") or "high").lower()


def _identity_ok(rec: Dict[str, Any], pol: Dict[str, Any]) -> bool:
    tokens = {str(t).upper() for t in (pol.get("identity_verified_tokens") or [])}
    status = str(rec.get("identity_status") or rec.get("verification_status") or "").upper()
    return bool(status in tokens and rec.get("entity_identity"))


def _pair_relation(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    ha, hb = str(a.get("content_hash") or ""), str(b.get("content_hash") or "")
    if ha and hb and ha == hb:
        return "syndicated_copied"
    oa, ob = str(a.get("original_source") or ""), str(b.get("original_source") or "")
    if oa and ob and oa == ob:
        return "same_original_source"
    da = registrable_domain(str(a.get("source_url_or_identifier") or ""))
    db = registrable_domain(str(b.get("source_url_or_identifier") or ""))
    if da and db and da == db:
        return "same_domain"
    pa, pb = str(a.get("provider") or "").upper(), str(b.get("provider") or "").upper()
    if pa and pb and pa == pb:
        return "same_provider"
    return "independent_source"


def classify_independence(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    relations: List[str] = []
    independent: List[Dict[str, Any]] = []
    consumed = set()
    for i, a in enumerate(records):
        aid = str(a.get("evidence_id"))
        if aid in consumed:
            continue
        consumed.add(aid)
        independent.append(a)
        for b in records[i + 1 :]:
            bid = str(b.get("evidence_id"))
            rel = _pair_relation(a, b)
            if rel != "independent_source":
                relations.append(rel)
                consumed.add(bid)
    if len(records) >= 2 and not relations:
        relations = ["independent_source"]
    return {
        "independent_count": len(independent),
        "independent_ids": [str(x.get("evidence_id")) for x in independent],
        "relations": sorted(set(relations)),
        "status": "INDEPENDENT" if len(independent) >= 2 else ("SINGLE" if records else "NONE"),
    }


def temporal_status(records: List[Dict[str, Any]], pol: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _now()
    days = pol.get("freshness_days")
    stale = False
    missing = False
    reasons: List[str] = []
    for rec in records:
        if _is_llm(rec, pol):
            continue
        retrieved = parse_dt(rec.get("retrieved_at"))
        observed = parse_dt(rec.get("observed_at")) or retrieved
        valid_to = parse_dt(rec.get("valid_to"))
        if valid_to and valid_to < now:
            stale = True
            reasons.append("VALID_TO_EXPIRED")
        if days is not None and observed and (now - observed).days > int(days):
            stale = True
            reasons.append("STALE_FOR_CLAIM")
        if days is not None and not observed:
            missing = True
            reasons.append("DATE_MISSING")
    ok = not stale and not (missing and bool(pol.get("missing_date_blocks_gold")))
    return {"ok": ok, "stale": stale, "missing": missing, "reasons": sorted(set(reasons))}


def memory_feedback(level: str, eclass: str, verified_result: bool, reasons: List[str], indep: Dict[str, Any], contradiction: bool) -> Dict[str, Any]:
    return {
        "evidence_quality": eclass,
        "verification_level": level,
        "verified_result": bool(verified_result),
        "failure_reason": ",".join(reasons),
        "contradictions_found": bool(contradiction),
        "source_independence_status": indep.get("status") or "NONE",
    }


def assess_claim(
    claim_id: str,
    claim_text: str = "",
    claim_type: str = "default",
    records: Optional[List[Dict[str, Any]]] = None,
    contrary_evidence: Optional[List[Dict[str, Any]]] = None,
    adversarial_completed: bool = False,
    adversarial_contrary_found: bool = False,
    policy: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    pol = claim_policy(claim_type, policy)
    rows = [evidence_record(**dict(r)) for r in (records or [])]
    contrary = list(contrary_evidence or [])
    for rec in rows:
        contrary.extend(rec.get("contrary_evidence") or [])
    now = now or _now()
    reasons: List[str] = []
    indep: Dict[str, Any] = {"independent_count": 0, "status": "NONE", "relations": []}
    temporal: Dict[str, Any] = {"ok": True, "stale": False, "missing": False, "reasons": []}

    if not rows:
        reasons.append("NO_EVIDENCE_RECORDS")
        mem = memory_feedback("INSUFFICIENT_EVIDENCE", "UNVERIFIED", False, reasons, indep, False)
        return _pack(claim_id, claim_text, pol, "INSUFFICIENT_EVIDENCE", "UNVERIFIED", False, reasons, indep, temporal, [], mem)

    llm_only = all(_is_llm(r, pol) for r in rows)
    world_only = all(_is_world(r, pol) for r in rows)
    has_external = any(not _is_llm(r, pol) for r in rows)
    contradiction = bool(contrary) or adversarial_contrary_found or any(r.get("contradictions") for r in rows)

    level = "RAW"
    eclass = "UNVERIFIED"
    bronze = any(
        bool(r.get("source_url_or_identifier") or r.get("source") or r.get("retrieved_at"))
        and bool(r.get("content_hash") or r.get("retrieved_at") or r.get("source_url_or_identifier"))
        for r in rows
    )
    if bronze:
        level = "BRONZE"

    ident_ok = True if not pol.get("require_identity_for_silver") else any(_identity_ok(r, pol) for r in rows)
    pert_ok = True if not pol.get("require_pertinence_for_silver") else any(bool(r.get("pertinence_ok", True)) for r in rows)
    if level == "BRONZE" and ident_ok and pert_ok and has_external and not llm_only:
        level = "SILVER"
    elif level == "BRONZE" and not ident_ok:
        reasons.append("IDENTITY_NOT_SUFFICIENT_FOR_SILVER")
    elif level == "BRONZE" and not pert_ok:
        reasons.append("PERTINENCE_NOT_SUFFICIENT_FOR_SILVER")

    external_rows = [r for r in rows if not _is_llm(r, pol)]
    indep = classify_independence(external_rows)
    temporal = temporal_status(rows, pol, now)
    official_ok = any(_is_official(r, pol) for r in external_rows)
    min_ind = int(pol.get("min_independent_for_gold") or 2)
    independence_ok = indep["independent_count"] >= min_ind or (
        bool(pol.get("allow_single_official_gold")) and official_ok and indep["independent_count"] >= 1
    )

    if llm_only:
        eclass = str(pol.get("max_class_if_llm_only") or "INFERENCE")
        level = str(pol.get("max_level_if_llm_only") or "INSUFFICIENT_EVIDENCE")
        reasons.append("LLM_SYNTHESIS_WITHOUT_EXTERNAL_EVIDENCE")
    elif world_only:
        eclass = str(pol.get("max_class") or "INDICATOR")
        if eclass == "VERIFIED_FACT":
            eclass = "INDICATOR"
        cap = str(pol.get("max_level") or "SILVER")
        if LEVEL_RANK.get(level, 0) > LEVEL_RANK.get(cap, 0) or level in {"GOLD", "GOLD_PLUS"}:
            level = cap if cap not in {"GOLD", "GOLD_PLUS"} else "SILVER"
        reasons.append("WORLD_CORRELATION_IS_NOT_GOLD")
        if eclass not in EVIDENCE_CLASSES:
            eclass = "CORRELATION"
    elif str(pol.get("max_class") or "") == "INFERENCE":
        eclass = "INFERENCE"
        level = str(pol.get("max_level") or "INSUFFICIENT_EVIDENCE")
        reasons.append("INFERENTIAL_CLAIM_CANNOT_BE_VERIFIED_FACT")
    elif contradiction:
        eclass = "CONFLICTING_EVIDENCE"
        level = "INSUFFICIENT_EVIDENCE"
        reasons.append("UNRESOLVED_CONTRADICTION")
    elif level == "SILVER":
        if not temporal["ok"]:
            reasons.extend(temporal.get("reasons") or ["TEMPORAL_FAIL"])
        elif not independence_ok:
            reasons.append("INSUFFICIENT_INDEPENDENT_SOURCES")
        else:
            level = "GOLD"
            eclass = "VERIFIED_FACT"

    if level == "GOLD" and bool(pol.get("allow_gold_plus")) and adversarial_completed and not contradiction:
        level = "GOLD_PLUS"
    if level == "GOLD_PLUS" and not pol.get("allow_gold_plus"):
        level = "GOLD"
        reasons.append("GOLD_PLUS_NOT_ALLOWED_BY_CLAIM_POLICY")
    if level == "GOLD_PLUS" and not adversarial_completed:
        level = "GOLD"
        reasons.append("ADVERSARIAL_NOT_COMPLETED")

    verified = level in {"GOLD", "GOLD_PLUS"}
    if verified:
        eclass = "VERIFIED_FACT"
    mem = memory_feedback(level, eclass, verified, reasons, indep, contradiction)
    return _pack(claim_id, claim_text, pol, level, eclass, verified, reasons, indep, temporal, rows, mem)


def _pack(claim_id, claim_text, pol, level, eclass, verified, reasons, indep, temporal, rows, mem) -> Dict[str, Any]:
    return {
        "version": VERSION,
        "claim_id": claim_id,
        "claim_text": claim_text,
        "claim_type": pol.get("claim_type"),
        "verification_level": level,
        "evidence_class": eclass,
        "verified_result": verified,
        "reasons": reasons,
        "independence": indep,
        "temporal": temporal,
        "records": rows,
        "memory": mem,
        "note": "AI output cannot mint GOLD. ENTITY_VERIFIED/EXPLICIT_NEED are not FACT_VERIFIED.",
    }


def evidence_from_ingestion_record(ing: Dict[str, Any]) -> Dict[str, Any]:
    """Map an Ingestion Record to RAW evidence. Never marks GOLD here."""
    errors = [str(e) for e in (ing.get("errors") or [])]
    missing = "MISSING_PROVENANCE" in errors
    url = "" if missing else str(ing.get("url") or ing.get("origin") or ing.get("raw_reference") or "")
    digest = "" if missing else str(ing.get("sha256") or "")
    payload = ing.get("normalized_payload")
    if payload is None:
        body = ""
    elif isinstance(payload, str):
        body = payload[:2000]
    else:
        body = json.dumps(payload, ensure_ascii=False, default=str)[:2000]
    stype = str(ing.get("source_type") or "WEB")
    family = str(ing.get("source_family") or "").upper()
    if family in {"SATELLITE", "GEO"} and stype.upper() not in {x.upper() for x in SATELLITE_TYPES_FALLBACK}:
        stype = "SATELLITE_IMAGERY"
    eclass = "INDICATOR" if family in {"SATELLITE", "GEO"} or stype.upper() in {x.upper() for x in SATELLITE_TYPES_FALLBACK} else "UNVERIFIED"
    if missing:
        eclass = "UNVERIFIED"
        stype = "UNPROVENANCED"
    return evidence_record(
        evidence_id=str(ing.get("ingestion_id") or ""),
        source=str(ing.get("provider") or ing.get("source_id") or ""),
        source_type=stype,
        source_url_or_identifier=url,
        provider=str(ing.get("provider") or ""),
        retrieved_at="" if missing else (ing.get("retrieved_at") or ""),
        observed_at="" if missing else (ing.get("observed_at") or ""),
        content=body,
        content_hash=digest,
        evidence_class=eclass,
        pertinence_ok=not missing,
        official=False,
        provenance={
            "ingestion_id": ing.get("ingestion_id"),
            "access_class": ing.get("access_class"),
            "raw_reference": "" if missing else ing.get("raw_reference"),
            "gateway": True,
            "mints_gold": False,
        },
    )


def evidence_from_pipeline_row(row: Dict[str, Any], retrieved_at: str = "") -> Dict[str, Any]:
    url = str(row.get("evidence_url") or row.get("detail_url") or row.get("source_url") or "")
    return evidence_record(
        claim_id=str(row.get("candidate_id") or ""),
        source=str(row.get("source") or ""),
        source_type="WEB",
        source_url_or_identifier=url,
        provider=str(row.get("discovery_method") or row.get("source") or ""),
        retrieved_at=retrieved_at or str(row.get("discovery_timestamp") or ""),
        observed_at=str(row.get("discovery_timestamp") or ""),
        content=str(row.get("evidence") or row.get("need_fact") or "")[:2000],
        entity_identity=str(row.get("entity_name") or ""),
        identity_status=str(row.get("verification_status") or ""),
        pertinence_ok=str(row.get("need_signal") or "") == "CONCRETE",
        official=False,
        provenance={"pipeline": True},
    )


def _sample(**kw: Any) -> Dict[str, Any]:
    return dict(kw)


def run_local_tests() -> Dict[str, Any]:
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    fresh = "2026-09-01T00:00:00+00:00"
    old = "2018-01-01T00:00:00+00:00"
    body = "studio evidenza business plan credito"
    h = content_hash(body)

    def chk(name: str, cond: bool, detail: Any) -> Dict[str, Any]:
        return {"id": name, "ok": bool(cond), "detail": detail}

    a = assess_claim("A", claim_type="simple_public_fact", now=now, records=[_sample(
        source="blog", source_type="WEB", source_url_or_identifier="https://example.net/post",
        provider="WEB1", retrieved_at=fresh, content=body, content_hash=h, pertinence_ok=True, trust="low")])
    t_a = chk("A", a["verification_level"] not in {"GOLD", "GOLD_PLUS"}, a["verification_level"])

    b = assess_claim("B", claim_type="simple_public_fact", now=now, records=[
        _sample(source="m1", source_type="WEB", source_url_or_identifier="https://aaa.example/p", provider="P1",
                retrieved_at=fresh, content=body, content_hash=h, pertinence_ok=True, trust="medium"),
        _sample(source="m2", source_type="WEB", source_url_or_identifier="https://bbb.example/p", provider="P2",
                retrieved_at=fresh, content=body, content_hash=h, pertinence_ok=True, trust="medium"),
    ])
    t_b = chk("B", b["independence"]["independent_count"] < 2 and b["verification_level"] not in {"GOLD", "GOLD_PLUS"},
              {"indep": b["independence"]["independent_count"], "level": b["verification_level"], "rel": b["independence"]["relations"]})

    c = assess_claim("C", claim_type="simple_public_fact", now=now, records=[
        _sample(source="gazette", source_type="OFFICIAL", source_url_or_identifier="https://gov.example/a", provider="GOV",
                retrieved_at=fresh, observed_at=fresh, content="alpha fact one", pertinence_ok=True, trust="high", official=True),
        _sample(source="istat", source_type="PRIMARY", source_url_or_identifier="https://istat.example/b", provider="ISTAT",
                retrieved_at=fresh, observed_at=fresh, content="alpha fact two", pertinence_ok=True, trust="high", official=True),
    ])
    t_c = chk("C", c["verification_level"] in {"GOLD", "GOLD_PLUS"} and c["evidence_class"] == "VERIFIED_FACT", c["verification_level"])

    d = assess_claim("D", claim_type="simple_public_fact", now=now, contrary_evidence=[{"id": "CTR"}], records=[
        _sample(source="gazette", source_type="OFFICIAL", source_url_or_identifier="https://gov.example/a", provider="GOV",
                retrieved_at=fresh, observed_at=fresh, content="yes", pertinence_ok=True, trust="high", official=True),
        _sample(source="court", source_type="PRIMARY", source_url_or_identifier="https://court.example/b", provider="COURT",
                retrieved_at=fresh, observed_at=fresh, content="no", pertinence_ok=True, trust="high", official=True,
                contradictions=["denies claim"]),
    ])
    t_d = chk("D", d["evidence_class"] == "CONFLICTING_EVIDENCE" and d["verification_level"] not in {"GOLD", "GOLD_PLUS"},
              {"class": d["evidence_class"], "level": d["verification_level"]})

    e = assess_claim("E", claim_type="default", now=now, records=[_sample(
        source="brain", source_type="LLM_SYNTHESIS", source_url_or_identifier="model:local", provider="BRAIN",
        retrieved_at=fresh, content="the model concludes X", pertinence_ok=True, trust="low")])
    t_e = chk("E", e["evidence_class"] == "INFERENCE" and e["verification_level"] not in {"GOLD", "GOLD_PLUS"},
              {"class": e["evidence_class"], "level": e["verification_level"]})

    f = assess_claim("F", claim_type="sensitive", now=now, records=[
        _sample(source="gazette", source_type="OFFICIAL", source_url_or_identifier="https://gov.example/old", provider="GOV",
                retrieved_at=old, observed_at=old, content="old status", pertinence_ok=True, trust="high", official=True),
        _sample(source="istat", source_type="PRIMARY", source_url_or_identifier="https://istat.example/old2", provider="ISTAT",
                retrieved_at=old, observed_at=old, content="also old", pertinence_ok=True, trust="high", official=True),
    ])
    t_f = chk("F", f["verification_level"] not in {"GOLD", "GOLD_PLUS"}, {"level": f["verification_level"], "temporal": f["temporal"]})

    import jarvis_source_intelligence_v5 as navmod
    nav = navmod.navigate(
        mission_goal="Cerca studi di commercialisti con bisogno verificabile di supporto per business plan.",
        world_context={"cities": ["Milano"], "status": "WORLD_READY"},
        available_capabilities=[
            {"id": "ROUTE_A_VERTICAL", "type": "VERTICAL_HTML", "domains": ["BUSINESS"],
             "mission_families": ["ODCEC_BACHECA", "COMMERCIAL_NEED_HUNT"], "geography": ["Milano"], "language": ["it"],
             "status": "READY", "cost": "FREE", "auth_required": False, "trust": "high", "historical_success": 0,
             "last_failure": "", "failure_reason": "", "specialized": True, "mode": "READ_ONLY", "query_family": "VERTICAL"},
            {"id": "ROUTE_B_GENERAL", "type": "GENERAL_SEARCH", "domains": ["BUSINESS"],
             "mission_families": ["NEED_PHRASE_HUNT", "COMMERCIAL_NEED_HUNT"], "geography": ["IT"], "language": ["it"],
             "status": "DEGRADED", "cost": "FREE", "auth_required": False, "trust": "medium", "historical_success": 0,
             "last_failure": "", "failure_reason": "", "specialized": False, "mode": "READ_ONLY", "query_family": "NEED"},
        ],
        security_policy={"network_mode": "READ_ONLY_PUBLIC"},
        budget={"max_replans": 3},
        gap_fn=lambda g, r: {"status": "SKIP"},
    )
    wrapped = navmod.verify_with_gate(nav, a, complete_if_gold=False)
    t_g = chk("G", wrapped.get("replanned") is True and wrapped.get("state") != "COMPLETE",
              {"state": wrapped.get("state"), "replanned": wrapped.get("replanned")})

    h = assess_claim("H", claim_type="simple_public_fact", now=now, adversarial_completed=True, records=[
        _sample(source="gazette", source_type="OFFICIAL", source_url_or_identifier="https://gov.example/a", provider="GOV",
                retrieved_at=fresh, observed_at=fresh, content="alpha fact one", pertinence_ok=True, trust="high", official=True),
        _sample(source="istat", source_type="PRIMARY", source_url_or_identifier="https://istat.example/b", provider="ISTAT",
                retrieved_at=fresh, observed_at=fresh, content="alpha fact two", pertinence_ok=True, trust="high", official=True),
    ])
    h2 = assess_claim("H2", claim_type="commercial_need", now=now, adversarial_completed=True, records=h["records"])
    t_h = chk("H", h["verification_level"] == "GOLD_PLUS" and h2["verification_level"] != "GOLD_PLUS",
              {"allowed": h["verification_level"], "denied": h2["verification_level"]})

    tests = [t_a, t_b, t_c, t_d, t_e, t_f, t_g, t_h]
    return {"version": VERSION, "ok": all(t["ok"] for t in tests), "tests": tests}


if __name__ == "__main__":
    out = run_local_tests()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if out.get("ok") else 1)
