"""JARVIS Open Core — one-command demo:  python demo.py

1. Ingestion gateway + Evidence Gold Gate: run their built-in test suites
   (unauthorised sources are refused, missing provenance never becomes GOLD, ...).
2. Strategy layer: an outgoing email stays BLOCKED until a human approves that exact content.
3. WORLD core: scores 3 Italian cities from a snapshot of public data (examples/cities_sample.json).

No network, no model, no external action. Temporary data goes to a throwaway folder.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("JARVIS_DATA_DIR", tempfile.mkdtemp(prefix="jarvis_open_core_"))
for sub in ("ARMS/RESEARCH", "ARMS/WORLD", "CORE"):
    sys.path.insert(0, str(HERE / sub))

import jarvis_evidence_gold_gate_v5 as gold  # noqa: E402
import jarvis_ingestion_gateway_v5 as gateway  # noqa: E402
import jarvis_strategy_layer_v1 as strategy  # noqa: E402
import jarvis_world_core_v4_clienti as world  # noqa: E402


def title(text: str) -> None:
    print(f"\n=== {text} ===")


def show_tests(name: str, out: dict) -> bool:
    passed = sum(1 for t in out["tests"] if t["ok"])
    print(f"{name}: {passed}/{len(out['tests'])} tests passed")
    for t in out["tests"]:
        if not t["ok"]:
            print(f"  FAILED {t['id']}: {t['detail']}")
    return bool(out["ok"])


def main() -> int:
    ok = True

    title("1. Ingestion gateway and Evidence Gold Gate")
    ok &= show_tests("Evidence Gold Gate", gold.run_local_tests())
    ok &= show_tests("Ingestion gateway", gateway.run_local_tests())
    refused = gateway.ingest({"source_id": "INFOCAMERE", "url": "https://example.invalid/registry",
                              "allow_network": False}, persist=False)
    print(f"Source needing a login (INFOCAMERE): access={refused['access_class']} errors={refused['errors'][:1]}")
    ok &= "ACQUIRE_REFUSED" in refused["errors"]

    title("2. Strategy layer: human approval before any external action")
    email = {"to": "editor@example.org", "subject": "Book proposal", "body": "Hello, ..."}
    first = strategy.request_action("email", email)
    print(f"Email without approval        -> {first['status']} ({first['reason']})")
    approval = strategy.approve("email", email, approved_by="owner")
    edited = dict(email, body="Hello, ... (changed after approval)")
    second = strategy.request_action("email", edited, approval)
    print(f"Approved, then content edited -> {second['status']} ({second['reason']})")
    third = strategy.request_action("email", email, approval)
    print(f"Approved, same content        -> {third['status']} (executed={third['executed']}: the gate never sends)")
    ok &= first["status"] == "BLOCKED" and second["status"] == "BLOCKED" and third["status"] == "READY_TO_EXECUTE"

    title("3. WORLD core: scoring 3 cities from public data")
    sample = json.loads((HERE / "examples" / "cities_sample.json").read_text(encoding="utf-8"))
    for r in world.punteggia(sample["cities"]):
        print(f"{r['citta']:<8} score {r['punteggio']:5.1f}  {r['livello']:<6} "
              f"(businesses {r['punteggi']['aziende']}, crisis news {r['punteggi']['crisi']}, population {r['punteggi']['popolazione']})")

    print("\nRESULT:", "ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
