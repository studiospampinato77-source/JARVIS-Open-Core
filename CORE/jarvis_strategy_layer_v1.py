"""JARVIS Strategy Layer V1 (open core).

Turns an objective into a mission plan and keeps every external action
(email, message, publish, payment) behind explicit human approval.

- plan(objective): picks a mission and asks a local model (Ollama) for an analysis.
  The model only writes text: it never performs actions.
- request_action(kind, payload, approval=None): the only door to the outside.
  Without a valid approval bound to the exact payload the action is BLOCKED.
  This module never sends anything itself: an approved action is returned
  as READY_TO_EXECUTE for an executor that the operator plugs in.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from datetime import datetime, timezone

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen3:8b")

MISSIONS = {
    "MAKE_MONEY": {
        "objective": "Find legitimate, evidence-backed economic opportunities.",
        "strategies": [
            "SME_SUPPORT",
            "BOOK",
            "COMMERCIAL",
        ],
    },

    "SME_SUPPORT": {
        "objective": "Find identifiable businesses with documented current needs.",
        "capabilities": [
            "RESEARCH",
            "CLIENT_INTELLIGENCE",
            "COMMERCIAL",
            "EVIDENCE",
            "WORLD_GEO",
            "OPPORTUNITY_STORE",
        ],
    },

    "BOOK": {
        "objective": "Find audiences and reachable channels with strong affinity and intent.",
        "capabilities": [
            "BOOK_SALES_ENGINE",
            "AUDIENCE_INTELLIGENCE",
            "READER_QUALIFIER",
            "RESEARCH",
            "SOURCE_INTELLIGENCE",
            "WORLD_GEO",
            "SOCIAL",
        ],
    },
}

EXTERNAL_ACTIONS = {
    "email": "APPROVAL_REQUIRED",
    "message": "APPROVAL_REQUIRED",
    "publish": "APPROVAL_REQUIRED",
    "payment": "APPROVAL_REQUIRED",
}


def choose_mission(objective) -> str:
    key = str(objective or "").strip().upper()
    if "LIBRO" in key or "BOOK" in key:
        return "BOOK"
    if "PMI" in key or "SME" in key or "CLIENT" in key or "CONSULEN" in key:
        return "SME_SUPPORT"
    return "MAKE_MONEY"


def plan(objective, use_model: bool = True):
    objective = str(objective or "").strip()
    mission = choose_mission(objective)
    analysis = ""
    if use_model:
        prompt = (
            "Sei il cervello strategico di JARVIS. Rispondi in italiano. "
            "Elabora una strategia concreta e personalizzata, non un piano generico. "
            "Indica obiettivi, azioni pratiche, ostacoli e priorità. "
            "Non dichiarare di aver eseguito azioni esterne. "
            "Richiesta: " + objective
        )
        payload = json.dumps({
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {"num_predict": 650}
        }).encode()
        req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as response:
            analysis = json.load(response).get("response", "").strip()

    return {
        "mission": mission,
        "plan": MISSIONS[mission],
        "analysis": analysis,
        "external_actions": EXTERNAL_ACTIONS,
        "principle": "Evidence before action; quality before volume."
    }


def action_hash(kind: str, payload: dict) -> str:
    """Fingerprint of the exact action: an approval is valid only for this content."""
    body = json.dumps({"kind": str(kind or "").lower(), "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def approve(kind: str, payload: dict, approved_by: str) -> dict:
    """Recorded by the human operator after reading the action (e.g. a "yes" in chat)."""
    if not str(approved_by or "").strip():
        raise ValueError("approved_by is required")
    return {"action_hash": action_hash(kind, payload), "approved_by": approved_by,
            "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def request_action(kind: str, payload: dict, approval: dict | None = None) -> dict:
    """Gate for every external action. Returns BLOCKED unless the approval matches this exact action."""
    kind = str(kind or "").lower()
    rule = EXTERNAL_ACTIONS.get(kind, "APPROVAL_REQUIRED")  # unknown actions are treated as external
    h = action_hash(kind, payload)
    if rule == "APPROVAL_REQUIRED":
        if not approval:
            return {"status": "BLOCKED", "reason": "APPROVAL_REQUIRED", "kind": kind, "action_hash": h}
        if approval.get("action_hash") != h:
            return {"status": "BLOCKED", "reason": "APPROVAL_DOES_NOT_MATCH_CONTENT", "kind": kind, "action_hash": h}
    return {"status": "READY_TO_EXECUTE", "kind": kind, "action_hash": h,
            "approved_by": (approval or {}).get("approved_by"), "executed": False}
