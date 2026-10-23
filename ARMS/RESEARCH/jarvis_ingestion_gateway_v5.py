#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JARVIS Ingestion Gateway V1.

Sole controlled entry for future external datasets.
Does not decide truth. Does not mint GOLD. Does not LLM-synthesize.
Does not call Copernicus/NASA/InfoCamere. Network off unless explicitly allowed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

VERSION = "5.3.6-INGESTION-GATEWAY"
HERE = Path(__file__).resolve().parent
MASTER = HERE.parents[1]
CATALOG_PATH = MASTER / "GOVERNANCE" / "ingestion_access_catalog_v5.json"
DATA_DIR = Path(os.getenv("JARVIS_DATA_DIR", str(MASTER / "data")))
STORE_DIR = DATA_DIR / "ingestion"
STORE_JSONL = STORE_DIR / "ingestion.jsonl"
RAW_REFS = STORE_DIR / "raw_refs"

ACCESS_CLASSES = (
    "PUBLIC_OPEN",
    "PUBLIC_LIMITED",
    "AUTH_REQUIRED",
    "LICENSE_RESTRICTED",
    "LOCAL_FILE",
    "UNAVAILABLE",
    "UNKNOWN",
)
REFUSE_NETWORK = {"AUTH_REQUIRED", "LICENSE_RESTRICTED", "UNAVAILABLE", "UNKNOWN"}
PAID_COSTS = {"PAID", "METERED"}
SATELLITE_FAMILIES = {"SATELLITE", "GEO"}
SATELLITE_TYPES = {"SATELLITE_IMAGERY", "GEO_DATASET", "WEATHER_CLIMATE"}
STAGES = (
    "SOURCE",
    "ACQUIRE",
    "VALIDATE",
    "NORMALIZE",
    "PROVENANCE",
    "HASH",
    "TIMESTAMP",
    "CLASSIFY",
    "STORE_REFERENCE",
    "PASS_TO_ROUTER_EVIDENCE",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_catalog() -> Dict[str, Any]:
    if CATALOG_PATH.exists():
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {"sources": [], "max_in_memory_bytes": 2097152, "csv_sample_rows": 20, "max_normalized_chars": 12000}


def gateway_contract() -> Dict[str, Any]:
    return {
        "implemented": True,
        "version": VERSION,
        "stages": list(STAGES),
        "access_classes": list(ACCESS_CLASSES),
        "mints_gold": False,
        "mints_verified_fact": False,
        "live_clients": False,
        "network_default": "OFF",
        "note": "Gateway produces OBSERVATION records. Gold Gate decides evidence level. Knowledge Library may index records without minting GOLD.",
        "pass_to": ["NAVIGATION_ROUTER", "EVIDENCE_GOLD_GATE", "KNOWLEDGE_LIBRARY"],
    }


def source_entry(source_id: str, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    catalog = catalog or _load_catalog()
    sid = str(source_id or "LOCAL_FILE").upper()
    for row in catalog.get("sources") or []:
        if str(row.get("source_id") or "").upper() == sid:
            return dict(row)
    return {
        "source_id": sid or "UNKNOWN",
        "provider": "UNKNOWN",
        "source_family": "UNKNOWN",
        "source_type": "UNKNOWN",
        "jurisdiction": "UNKNOWN",
        "geography": "UNKNOWN",
        "access_class": "UNKNOWN",
        "license": "UNDECLARED",
        "cost": "UNKNOWN",
        "auth_required": True,
        "live_client": False,
        "offline_ok": True,
    }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def guess_format(path: Optional[Path], mime: str, payload: Optional[bytes]) -> str:
    suffix = (path.suffix.lower() if path else "")
    mapping = {
        ".json": "json",
        ".csv": "csv",
        ".xml": "xml",
        ".html": "html",
        ".htm": "html",
        ".pdf": "pdf",
        ".txt": "txt",
        ".docx": "docx",
        ".xlsx": "xlsx",
        ".tif": "geotiff",
        ".tiff": "geotiff",
        ".nc": "netcdf",
        ".rss": "xml",
    }
    if suffix in mapping:
        return mapping[suffix]
    if suffix:
        return "unsupported"
    low = (mime or "").lower()
    if "json" in low:
        return "json"
    if "csv" in low:
        return "csv"
    if "xml" in low:
        return "xml"
    if "html" in low:
        return "html"
    if "pdf" in low:
        return "pdf"
    if payload:
        head = payload[:256].lstrip()
        if head.startswith(b"{") or head.startswith(b"["):
            return "json"
        if head.startswith(b"<"):
            return "xml" if b"<html" not in head[:64].lower() else "html"
    return "binary"


def empty_record(**kwargs: Any) -> Dict[str, Any]:
    rec = {
        "ingestion_id": "",
        "source_id": "",
        "provider": "",
        "source_family": "",
        "source_type": "",
        "jurisdiction": "",
        "geography": "",
        "retrieved_at": "",
        "observed_at": None,
        "origin": "",
        "url": "",
        "access_class": "UNKNOWN",
        "license": "UNDECLARED",
        "mime": "",
        "data_format": "",
        "sha256": "",
        "raw_reference": "",
        "normalized_payload": None,
        "normalized_reference": "",
        "freshness": "UNKNOWN",
        "technical_quality": 0.0,
        "errors": [],
        "warnings": [],
        "metadata": {},
        "duplicate_of": "",
        "conflict_group": "",
        "offline": True,
        "mints_gold": False,
        "evidence_hint": "UNVERIFIED",
        "version": VERSION,
    }
    rec.update(kwargs)
    return rec


def _freshness(observed_at: Optional[str], retrieved_at: str) -> str:
    if not observed_at:
        return "OBSERVED_AT_MISSING"
    if observed_at == retrieved_at:
        return "OBSERVED_EQUALS_RETRIEVED"
    try:
        obs = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
        ret = datetime.fromisoformat(str(retrieved_at).replace("Z", "+00:00"))
        if obs > ret:
            return "OBSERVED_AFTER_RETRIEVED"
        delta = (ret - obs).days
        if delta > 365:
            return "STALE_OBSERVATION"
        return "HISTORICAL_OK"
    except Exception:
        return "UNPARSABLE_DATES"


def _quality(errors: List[str], warnings: List[str], has_hash: bool, has_origin: bool, parsed: bool) -> float:
    if "MISSING_PROVENANCE" in errors or "ACQUIRE_REFUSED" in errors:
        return 0.0
    score = 0.2
    if has_origin:
        score += 0.25
    if has_hash:
        score += 0.25
    if parsed:
        score += 0.2
    score -= min(0.3, 0.05 * len(warnings))
    if errors:
        score = min(score, 0.35)
    return round(max(0.0, min(1.0, score)), 3)


def _normalize(fmt: str, raw: Optional[bytes], catalog: Dict[str, Any], large: bool, path: Optional[Path] = None) -> tuple[Any, List[str], List[str], bool]:
    errors: List[str] = []
    warnings: List[str] = []
    if fmt in {"pdf", "txt", "docx", "xlsx"}:
        try:
            if fmt == "pdf":
                from jarvis_knowledge_library_v5 import extract_pdf_local  # noqa: F401
            else:
                from jarvis_document_readers_v5 import extract_office_document  # noqa: F401
        except ImportError:
            errors.append(f"READER_NOT_INCLUDED:{fmt.upper()}")
            return None, warnings, errors, False
    if fmt == "pdf":
        from jarvis_knowledge_library_v5 import extract_pdf_local

        extracted = extract_pdf_local(raw=raw, path=str(path) if path else "")
        st = str(extracted.get("parse_status") or "")
        warnings.extend(list(extracted.get("warnings") or []))
        empty_pages = [p for p in (extracted.get("pages") or []) if not str(p.get("text") or "").strip()]
        if st != "PARSE_FAIL" and st != "ENCRYPTED" and empty_pages and path:
            from jarvis_ocr_reader_v5 import apply_ocr_to_native

            extracted = apply_ocr_to_native(
                extracted,
                str(path),
                sha256="",
                ingestion_id="",
            )
            st = str(extracted.get("parse_status") or st)
            warnings.extend(list(extracted.get("warnings") or []))
        payload = {
            "kind": extracted.get("kind") or "PDF_TEXT",
            "page_count": extracted.get("page_count") or 0,
            "pages": extracted.get("pages") or [],
            "parse_status": st,
            "pdf_library": extracted.get("pdf_library") or "pypdf",
            "ocr_applied": bool(extracted.get("ocr_applied")),
            "ocr_pages": list(extracted.get("ocr_pages") or []),
            "ocr_engine": extracted.get("ocr_engine") or "",
            "mints_gold": False,
            "is_verified_fact": False,
        }
        if st == "PARSE_FAIL":
            errors.append("PARSE_FAIL:PDF")
            if extracted.get("error"):
                errors.append(str(extracted.get("error")))
            return None, warnings, errors, False
        if st in {"OCR_REQUIRED", "ENCRYPTED", "OCR_FAIL"}:
            warnings.append(st)
            return payload, warnings, errors, False
        return payload, warnings, errors, True
    if fmt in {"txt", "docx", "xlsx"}:
        from jarvis_document_readers_v5 import extract_office_document

        extracted = extract_office_document(fmt, path=str(path) if path else "", raw=raw)
        st = str(extracted.get("parse_status") or "")
        warnings.extend(list(extracted.get("warnings") or []))
        payload = {
            "kind": extracted.get("kind") or fmt.upper(),
            "parse_status": st if st.startswith("OK") else st,
            "blocks": extracted.get("blocks") or [],
            "encoding": extracted.get("encoding") or "",
            "sheets": extracted.get("sheets") or [],
            "n_lines": extracted.get("n_lines"),
            "n_paragraphs": extracted.get("n_paragraphs"),
            "n_tables": extracted.get("n_tables"),
            "retrieval_text": extracted.get("retrieval_text") or "",
            "mints_gold": False,
            "is_verified_fact": False,
        }
        if st.startswith("PARSE_FAIL"):
            errors.append(st if ":" in st else f"PARSE_FAIL:{fmt.upper()}")
            if extracted.get("error"):
                errors.append(str(extracted.get("error")))
            return None, warnings, errors, False
        return payload, warnings, errors, True
    if fmt == "unsupported":
        errors.append("UNSUPPORTED_FORMAT")
        return None, warnings, errors, False
    if large or raw is None:
        return {"kind": "REFERENCE_ONLY"}, warnings, errors, True
    max_chars = int(catalog.get("max_normalized_chars") or 12000)
    sample_rows = int(catalog.get("csv_sample_rows") or 20)
    try:
        if fmt == "json":
            obj = json.loads(raw.decode("utf-8"))
            return {"kind": "JSON", "value": obj}, warnings, errors, True
        if fmt == "csv":
            text = raw.decode("utf-8", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            rows = []
            for i, row in enumerate(reader):
                if i >= sample_rows:
                    warnings.append("CSV_SAMPLED")
                    break
                rows.append(dict(row))
            return {"kind": "CSV", "columns": list(reader.fieldnames or []), "n_sampled": len(rows), "sample": rows}, warnings, errors, True
        if fmt == "xml":
            root = ET.fromstring(raw)
            return {"kind": "XML", "root_tag": root.tag, "n_children": len(list(root))}, warnings, errors, True
        if fmt == "html":
            text = raw.decode("utf-8", errors="replace")[:max_chars]
            return {"kind": "HTML", "excerpt": text}, warnings, errors, True
        if fmt in {"geotiff", "netcdf"}:
            warnings.append("RASTER_NOT_LOADED")
            return {"kind": "GEOSPATIAL_REFERENCE"}, warnings, errors, True
        excerpt = raw[:max_chars]
        return {"kind": "BYTES_EXCERPT", "n": len(raw), "head_hex": excerpt[:32].hex()}, warnings, errors, True
    except Exception as exc:
        errors.append(f"PARSE_FAIL:{type(exc).__name__}")
        return None, warnings, errors, False


def _load_index(store_path: Path) -> List[Dict[str, Any]]:
    if not store_path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in store_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _append(store_path: Path, rec: Dict[str, Any]) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with store_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def ingest(
    request: Optional[Dict[str, Any]] = None,
    *,
    store_path: Optional[Path] = None,
    persist: bool = True,
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """SOURCE → ACQUIRE → VALIDATE → NORMALIZE → PROVENANCE → HASH → STORE.

    allow_network defaults False. Live clients are not implemented.
    """
    req = dict(request or {})
    catalog = catalog or _load_catalog()
    src = source_entry(str(req.get("source_id") or "LOCAL_FILE"), catalog)
    for key in ("provider", "source_family", "source_type", "jurisdiction", "geography", "license", "access_class"):
        if req.get(key):
            src[key] = req[key]
    retrieved_at = _now()
    observed_at = req.get("observed_at")
    if observed_at == "":
        observed_at = None
    path = Path(req["path"]).expanduser() if req.get("path") else None
    origin = str(req.get("origin") or req.get("url") or (str(path) if path else ""))
    url = str(req.get("url") or "")
    errors: List[str] = []
    warnings: List[str] = []
    metadata: Dict[str, Any] = dict(req.get("metadata") or {})
    if path is not None:
        metadata.setdefault("filename", path.name)
        metadata.setdefault("source_origin", str(path))
    for field in (
        "title",
        "author",
        "publisher",
        "publication_date",
        "document_type",
        "domains",
        "language",
        "page_count",
        "filename",
        "source_origin",
    ):
        if req.get(field) is not None and field not in metadata:
            metadata[field] = req[field]
    access = str(src.get("access_class") or "UNKNOWN").upper()
    cost = str(src.get("cost") or "").upper()
    allow_network = bool(req.get("allow_network", False))
    max_mem = int(req.get("max_in_memory_bytes") or catalog.get("max_in_memory_bytes") or 2097152)

    if access not in ACCESS_CLASSES:
        access = "UNKNOWN"
        warnings.append("ACCESS_CLASS_UNKNOWN_COERCED")

    raw: Optional[bytes] = None
    large = False
    mime = str(req.get("mime") or "")
    fmt = str(req.get("data_format") or "")
    digest = ""
    raw_reference = origin
    acquired = False

    if cost in PAID_COSTS and not req.get("paid_authorized"):
        errors.append("ACQUIRE_REFUSED")
        errors.append("PAID_SOURCE_NOT_AUTO")
    elif src.get("live_client"):
        errors.append("ACQUIRE_REFUSED")
        errors.append("LIVE_CLIENT_NOT_IMPLEMENTED")
    elif allow_network:
        errors.append("ACQUIRE_REFUSED")
        errors.append("NETWORK_INGEST_DISABLED_V1")
    elif access in {"AUTH_REQUIRED", "LICENSE_RESTRICTED", "UNAVAILABLE"} and not path and req.get("payload") is None:
        errors.append("ACQUIRE_REFUSED")
        errors.append(f"ACCESS_CLASS_{access}")
    else:
        payload = req.get("payload")
        if payload is not None:
            raw = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
            acquired = True
            raw_reference = origin or "payload:inline"
        elif path is not None:
            if not path.exists() or not path.is_file():
                errors.append("ACQUIRE_FAIL")
                errors.append("LOCAL_FILE_MISSING")
            else:
                size = path.stat().st_size
                metadata["size_bytes"] = size
                mime = mime or (mimetypes.guess_type(str(path))[0] or "")
                digest = sha256_file(path)
                raw_reference = str(path.resolve())
                acquired = True
                if size > max_mem:
                    large = True
                    warnings.append("TOO_LARGE_REFERENCE_ONLY")
                else:
                    raw = path.read_bytes()
                if access != "LOCAL_FILE" and not url:
                    access = "LOCAL_FILE"
                    warnings.append("FORCED_LOCAL_FILE_ACCESS")
        elif url or str(req.get("origin") or "").startswith("http"):
            try:
                from jarvis_research_adapter_v5 import acquire_for_ingestion

                fetched = acquire_for_ingestion(url or origin, allow_network=False)
                errors.append("ACQUIRE_REFUSED")
                errors.append(str(fetched.get("error") or "NETWORK_DISABLED"))
            except Exception:
                errors.append("ACQUIRE_REFUSED")
                errors.append("NETWORK_DISABLED")
        else:
            errors.append("ACQUIRE_FAIL")
            errors.append("NO_LOCAL_SOURCE")

    if acquired and raw is not None and not digest:
        digest = sha256_bytes(raw)
    if acquired and not digest and path:
        digest = sha256_file(path)

    has_provenance = bool(origin or src.get("source_id") not in {"", "UNKNOWN"} or path)
    if not has_provenance or (not origin and not path and req.get("payload") is None and not url):
        if req.get("strip_provenance"):
            origin = ""
            url = ""
            src["source_id"] = ""
            src["provider"] = ""
            has_provenance = False
            errors.append("MISSING_PROVENANCE")
    if req.get("strip_provenance"):
        origin = ""
        url = ""
        src["source_id"] = ""
        src["provider"] = ""
        raw_reference = ""
        errors.append("MISSING_PROVENANCE")
        has_provenance = False

    if not fmt:
        fmt = guess_format(path, mime, raw)
    if not mime:
        mime = mimetypes.guess_type("x." + fmt)[0] or ""

    parsed = False
    normalized: Any = None
    if acquired and "PARSE_FAIL" not in "".join(errors) and "ACQUIRE_REFUSED" not in errors and "ACQUIRE_FAIL" not in errors:
        family = str(src.get("source_family") or "").upper()
        stype = str(src.get("source_type") or "").upper()
        if family in SATELLITE_FAMILIES or stype in SATELLITE_TYPES or fmt in {"geotiff", "netcdf"}:
            warnings.append("SATELLITE_GEO_IS_INDICATOR")
            if large or fmt in {"geotiff", "netcdf"}:
                normalized = {"kind": "GEOSPATIAL_REFERENCE", "format": fmt}
                parsed = True
                if raw is not None:
                    warnings.append("RASTER_BYTES_NOT_EXPANDED")
            else:
                normalized, w2, e2, parsed = _normalize(fmt, raw, catalog, large, path=path)
                warnings.extend(w2)
                errors.extend(e2)
                if isinstance(normalized, dict):
                    normalized["indicator_only"] = True
        else:
            normalized, w2, e2, parsed = _normalize(fmt, raw, catalog, large, path=path)
            warnings.extend(w2)
            errors.extend(e2)
    elif req.get("payload") is not None and "MISSING_PROVENANCE" in errors:
        normalized, w2, e2, parsed = _normalize(fmt, raw, catalog, False, path=path)
        warnings.extend(w2)
        errors.extend(e2)

    if isinstance(normalized, dict) and normalized.get("page_count") is not None:
        metadata["page_count"] = normalized.get("page_count")
        metadata["pdf_parse_status"] = normalized.get("parse_status") or ""

    if "PARSE_FAIL" in "".join(errors) or "UNSUPPORTED_FORMAT" in "".join(errors):
        parsed = False
        normalized = None

    store = Path(store_path) if store_path else STORE_JSONL
    duplicate_of = ""
    if digest:
        for prev in _load_index(store):
            if str(prev.get("sha256") or "") == digest and str(prev.get("ingestion_id") or ""):
                duplicate_of = str(prev.get("ingestion_id"))
                warnings.append("DUPLICATE_HASH_KEPT")
                break

    conflict_group = ""
    conflict_key = str(req.get("conflict_key") or "")
    if conflict_key:
        conflict_group = sha256_bytes(conflict_key.encode("utf-8"))[:16]
        for prev in _load_index(store):
            if str(prev.get("conflict_group") or "") == conflict_group and str(prev.get("sha256") or "") and str(prev.get("sha256")) != digest:
                warnings.append("CONFLICTING_SOURCE_KEPT")
                break

    family = str(src.get("source_family") or "").upper()
    stype = str(src.get("source_type") or "").upper()
    if family in SATELLITE_FAMILIES or stype in SATELLITE_TYPES:
        evidence_hint = "INDICATOR"
    elif not has_provenance:
        evidence_hint = "UNVERIFIED"
    else:
        evidence_hint = "UNVERIFIED"

    rec = empty_record(
        source_id=str(src.get("source_id") or ""),
        provider=str(src.get("provider") or ""),
        source_family=str(src.get("source_family") or ""),
        source_type=str(src.get("source_type") or ""),
        jurisdiction=str(src.get("jurisdiction") or ""),
        geography=str(src.get("geography") or ""),
        retrieved_at=retrieved_at,
        observed_at=observed_at,
        origin=origin,
        url=url,
        access_class=access,
        license=str(src.get("license") or "UNDECLARED"),
        mime=mime,
        data_format=fmt,
        sha256=digest,
        raw_reference=raw_reference,
        normalized_payload=normalized,
        normalized_reference=raw_reference if large else "",
        freshness=_freshness(str(observed_at) if observed_at else None, retrieved_at),
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
        metadata=metadata,
        duplicate_of=duplicate_of,
        conflict_group=conflict_group,
        offline=True,
        mints_gold=False,
        evidence_hint=evidence_hint,
        stages=list(STAGES),
    )
    rec["technical_quality"] = _quality(rec["errors"], rec["warnings"], bool(digest), has_provenance, parsed)
    rec["ingestion_id"] = "ING-" + sha256_bytes(
        (digest + retrieved_at + origin + rec["source_id"]).encode("utf-8")
    )[:16].upper()
    if persist and "ACQUIRE_FAIL" not in rec["errors"]:
        RAW_REFS.mkdir(parents=True, exist_ok=True)
        _append(store, rec)
    rec["pass_to"] = ["NAVIGATION_ROUTER", "EVIDENCE_GOLD_GATE", "KNOWLEDGE_LIBRARY"]
    rec["not_pass_to_as_gold"] = True
    if req.get("index_library"):
        try:
            from jarvis_knowledge_library_v5 import shelve_ingestion

            lib_path = Path(req["library_store"]) if req.get("library_store") else None
            rec["library"] = shelve_ingestion(rec, store_path=lib_path, persist=bool(persist))
        except Exception as exc:
            rec["library"] = {"ok": False, "indexed": False, "status": "LIBRARY_HANDOFF_FAIL", "reason": type(exc).__name__}
    return rec


def ingest_to_evidence(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Hand off to Gold Gate without minting GOLD here."""
    from jarvis_evidence_gold_gate_v5 import assess_claim, evidence_from_ingestion_record

    evidence = evidence_from_ingestion_record(rec)
    claim_type = "world_indicator" if rec.get("evidence_hint") == "INDICATOR" else "default"
    if "MISSING_PROVENANCE" in (rec.get("errors") or []):
        claim_type = "default"
    return assess_claim(
        rec.get("ingestion_id") or "ING",
        claim_text=str((rec.get("normalized_payload") or "") )[:500],
        claim_type=claim_type,
        records=[evidence],
    )


def run_local_tests() -> Dict[str, Any]:
    import tempfile

    from jarvis_evidence_gold_gate_v5 import assess_claim, evidence_from_ingestion_record
    from jarvis_experience_loop_v5 import contextual_score, experience_record
    from jarvis_source_intelligence_v5 import ingestion_gateway_contract

    tmp = Path(tempfile.mkdtemp(prefix="jarvis_ing_"))
    store = tmp / "ingestion.jsonl"
    catalog = _load_catalog()

    def chk(name: str, cond: bool, detail: Any) -> Dict[str, Any]:
        return {"id": name, "ok": bool(cond), "detail": detail}

    json_path = tmp / "ok.json"
    json_path.write_text('{"city":"Milano","value":1}', encoding="utf-8")
    a = ingest({"source_id": "LOCAL_FILE", "path": str(json_path), "observed_at": "2024-01-01T00:00:00+00:00"}, store_path=store, persist=True, catalog=catalog)
    t_a = chk("A", a["data_format"] == "json" and a["sha256"] and a["normalized_payload"] and a["mints_gold"] is False and a["retrieved_at"] != a["observed_at"], {"fmt": a["data_format"], "hash": bool(a["sha256"]), "fresh": a["freshness"]})

    csv_path = tmp / "ok.csv"
    csv_path.write_text("name,need\nAlpha,credit\n", encoding="utf-8")
    b = ingest({"source_id": "LOCAL_FILE", "path": str(csv_path)}, store_path=store, persist=True, catalog=catalog)
    t_b = chk("B", b["data_format"] == "csv" and (b.get("normalized_payload") or {}).get("n_sampled") == 1, b.get("normalized_payload"))

    dup_path = tmp / "dup.json"
    dup_path.write_text('{"city":"Milano","value":1}', encoding="utf-8")
    c = ingest({"source_id": "LOCAL_FILE", "path": str(dup_path)}, store_path=store, persist=True, catalog=catalog)
    t_c = chk("C", bool(c.get("duplicate_of")) and c["sha256"] == a["sha256"] and c["ingestion_id"] != a["ingestion_id"], {"dup": c.get("duplicate_of"), "kept": True})

    d1 = ingest({"source_id": "ISTAT", "path": str(json_path), "conflict_key": "pop:milano", "payload": b'{"n":1}'}, store_path=store, persist=True, catalog=catalog)
    d2 = ingest({"source_id": "EUROSTAT", "conflict_key": "pop:milano", "payload": b'{"n":2}', "path": str(tmp / "x.json")}, store_path=store, persist=False, catalog=catalog)
    euro = tmp / "euro.json"
    euro.write_text('{"n":2}', encoding="utf-8")
    d2 = ingest({"source_id": "EUROSTAT", "path": str(euro), "conflict_key": "pop:milano"}, store_path=store, persist=True, catalog=catalog)
    t_d = chk("D", d1["conflict_group"] == d2["conflict_group"] and d1["sha256"] != d2["sha256"] and "CONFLICTING_SOURCE_KEPT" in d2["warnings"], {"g": d1["conflict_group"], "w": d2["warnings"]})

    old = ingest({"source_id": "LOCAL_FILE", "path": str(json_path), "observed_at": "2015-06-01T00:00:00+00:00"}, store_path=store, persist=True, catalog=catalog)
    t_e = chk("E", old["observed_at"] != old["retrieved_at"] and old["freshness"] == "STALE_OBSERVATION", {"obs": old["observed_at"], "ret": old["retrieved_at"], "fresh": old["freshness"]})

    f = ingest({"source_id": "INFOCAMERE", "url": "https://example.invalid/infocamere", "allow_network": False}, store_path=store, persist=False, catalog=catalog)
    t_f = chk("F", "ACQUIRE_REFUSED" in f["errors"] and f["access_class"] == "AUTH_REQUIRED" and not f["sha256"], {"errors": f["errors"], "class": f["access_class"]})

    big = tmp / "big.bin"
    big.write_bytes(b"X" * 64)
    g = ingest({"source_id": "COPERNICUS", "path": str(big), "max_in_memory_bytes": 16, "source_family": "SATELLITE", "source_type": "SATELLITE_IMAGERY"}, store_path=store, persist=True, catalog=catalog)
    t_g = chk("G", "TOO_LARGE_REFERENCE_ONLY" in g["warnings"] and g["normalized_payload"] and g["normalized_payload"].get("kind") in {"GEOSPATIAL_REFERENCE", "REFERENCE_ONLY"} and g["raw_reference"], {"warnings": g["warnings"], "payload": g["normalized_payload"]})

    h = ingest({"payload": b'{"x":1}', "strip_provenance": True}, store_path=store, persist=False, catalog=catalog)
    h_ev = evidence_from_ingestion_record(h)
    h_gold = assess_claim("H-ING", claim_type="simple_public_fact", records=[h_ev])
    t_h = chk("H", "MISSING_PROVENANCE" in h["errors"] and h_gold["verification_level"] not in {"GOLD", "GOLD_PLUS"} and h_gold["evidence_class"] != "VERIFIED_FACT", {"gold": h_gold["verification_level"], "class": h_gold["evidence_class"]})

    sat = tmp / "scene.json"
    sat.write_text('{"scene_id":"S2-FAKE","cloud":0.1}', encoding="utf-8")
    i_rec = ingest({"source_id": "COPERNICUS", "path": str(sat), "source_family": "SATELLITE", "source_type": "SATELLITE_IMAGERY", "observed_at": "2020-01-01T00:00:00+00:00"}, store_path=store, persist=True, catalog=catalog)
    i_gold = ingest_to_evidence(i_rec)
    from jarvis_experience_loop_v5 import load_policy as xp_policy

    xp = contextual_score(
        "COMMERCIAL",
        "INGEST_SAT",
        [experience_record(
            mission_family="COMMERCIAL",
            capability_id="INGEST_SAT",
            provider="COPERNICUS",
            timestamp=_now(),
            verification_level="INSUFFICIENT_EVIDENCE",
            verified_result=False,
            evidence_class="UNVERIFIED",
            technical_success=True,
        )],
        policy=xp_policy(),
    )
    t_i = chk(
        "I",
        i_rec["evidence_hint"] == "INDICATOR"
        and i_gold["verification_level"] not in {"GOLD", "GOLD_PLUS"}
        and i_gold["evidence_class"] in {"INDICATOR", "UNVERIFIED", "CORRELATION"}
        and xp["positive"] == 0,
        {"hint": i_rec["evidence_hint"], "level": i_gold["verification_level"], "class": i_gold["evidence_class"], "xp": xp},
    )

    bad = tmp / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    j = ingest({"source_id": "LOCAL_FILE", "path": str(bad)}, store_path=store, persist=True, catalog=catalog)
    t_j = chk("J", any(e.startswith("PARSE_FAIL") for e in j["errors"]) and j["normalized_payload"] is None, {"errors": j["errors"]})

    contract = ingestion_gateway_contract()
    t_k = chk("K_CONTRACT", contract.get("implemented") is True and contract.get("mints_gold") is False, contract)

    tests = [t_a, t_b, t_c, t_d, t_e, t_f, t_g, t_h, t_i, t_j, t_k]
    return {
        "version": VERSION,
        "ok": all(t["ok"] for t in tests),
        "tests": tests,
        "network_activated": False,
        "live_clients": False,
        "tmp": str(tmp),
    }


if __name__ == "__main__":
    out = run_local_tests()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if out.get("ok") else 1)
