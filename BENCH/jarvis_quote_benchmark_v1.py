"""JARVIS quote benchmark V1 — do open models quote the source, or invent it?

For each public document in the corpus the model must answer a question using ONLY that text and
return the exact passages it relies on. Quality is checked mechanically, not by another model:
a quote counts only if it is found word for word in the source (after normalising spaces,
quotes and case). We also measure speed.

Modes:
  short (default)  the model sees only the article that answers the question
  long             the model sees ALL articles of the corpus together and must quote the right one:
                   a quote counts only if it comes from the article that answers the question

Backends:
  ollama  (default)  local server, OLLAMA_URL (default http://127.0.0.1:11434)
  openai             any OpenAI-compatible endpoint (GPU providers): --base-url, key in the env var
                     named by --api-key-env (never on the command line)
  atlas              Atlas Cloud (https://api.atlascloud.ai/v1, OpenAI-compatible), key in ATLASCLOUD_API_KEY

Usage:
  python BENCH/jarvis_quote_benchmark_v1.py --models qwen3:8b gemma3:4b
  python BENCH/jarvis_quote_benchmark_v1.py --backend atlas --models qwen/qwen3.5-27b deepseek-ai/deepseek-v4.1-flash
         (Atlas Cloud, key in ATLASCLOUD_API_KEY)
  python BENCH/jarvis_quote_benchmark_v1.py --backend openai --base-url https://api.example.com/v1 \
         --api-key-env PROVIDER_API_KEY --models some-open-model-70b
Results: BENCH/results/<timestamp>.json and a Markdown table on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus_it_law.json"
RESULTS = HERE / "results"

PROMPT = """Rispondi alla domanda usando SOLO il testo qui sotto.
Rispondi con un oggetto JSON e nient'altro, in questa forma:
{{"answer": "risposta breve in italiano", "quotes": ["frase copiata parola per parola dal testo", "..."]}}
Le citazioni devono essere copiate esattamente dal testo, da 1 a 3, ciascuna di almeno 8 parole.

TESTO:
{text}

DOMANDA: {question}"""


def norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("«", '"').replace("»", '"')
    s = re.sub(r"[()]{2}", "", s)  # Normattiva marks amended text with (( ))
    return re.sub(r"\s+", " ", s).strip().lower().strip(' ."')


def check_quotes(quotes: list, source: str) -> dict:
    src = norm(source)
    found = [q for q in quotes if isinstance(q, str) and len(norm(q).split()) >= 4 and norm(q) in src]
    return {"quotes_count": len(quotes), "found": len(found)}


def parse_json(text: str):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def call_ollama(model: str, prompt: str) -> dict:
    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/generate"
    body = {"model": model, "prompt": prompt, "stream": False, "think": False, "format": "json",
            "options": {"temperature": 0, "num_ctx": 8192}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        d = json.load(r)
    toks, dur = d.get("eval_count") or 0, (d.get("eval_duration") or 0) / 1e9
    return {"text": d.get("response", ""), "output_tokens": toks, "tokens_per_s": round(toks / dur, 2) if dur else None}


# OpenAI-compatible providers with a preset: name -> (base URL, environment variable holding the key)
PROVIDERS = {"atlas": ("https://api.atlascloud.ai/v1", "ATLASCLOUD_API_KEY")}


def call_openai(model: str, prompt: str, base_url: str, api_key_env: str) -> dict:
    key = os.getenv(api_key_env, "")
    if not key:
        raise SystemExit(f"set the API key in the environment variable {api_key_env}")
    body = {"model": model, "temperature": 0, "max_tokens": 1500, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                          "User-Agent": "JARVIS-Open-Core-benchmark/1.0"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.load(r)
    toks = (d.get("usage") or {}).get("completion_tokens") or 0
    dur = time.time() - t0
    return {"text": d["choices"][0]["message"]["content"], "output_tokens": toks,
            "tokens_per_s": round(toks / dur, 2) if dur and toks else None}


def _load():
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except OSError:
        return None


def run(models: list, backend: str, base_url: str = "", api_key_env: str = "", limit: int = 0, mode: str = "short") -> dict:
    load_avg = _load()
    items = json.loads(CORPUS.read_text(encoding="utf-8"))["items"]
    everything = "\n\n".join(i["text"] for i in items)
    if limit:
        items = items[:limit]
    rows = []
    for model in models:
        for it in items:
            prompt = PROMPT.format(text=everything if mode == "long" else it["text"], question=it["question"])
            t0 = time.time()
            try:
                out = call_ollama(model, prompt) if backend == "ollama" else call_openai(model, prompt, base_url, api_key_env)
                err = ""
            except Exception as e:  # one failure does not stop the run
                out, err = {"text": "", "output_tokens": 0, "tokens_per_s": None}, f"{type(e).__name__}: {e}"[:200]
            secs = round(time.time() - t0, 1)
            data = parse_json(out["text"])
            quotes = (data or {}).get("quotes") or []
            q = check_quotes(quotes if isinstance(quotes, list) else [], it["text"])
            rows.append({"model": model, "mode": mode, "item": it["id"], "seconds": secs, "tokens_per_s": out["tokens_per_s"],
                         "valid_json": data is not None, "answer": (data or {}).get("answer", ""),
                         "quotes": quotes, **q, "error": err})
            print(f"{model:<22} {it['id']:<10} {secs:7.1f}s  json={'ok' if data else 'NO':<3} quotes {q['found']}/{q['quotes_count']}", flush=True)
    return {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "backend": backend, "mode": mode,
            "hardware": {"machine": platform.machine(), "cpus": os.cpu_count(), "note": os.getenv("BENCH_HARDWARE", ""),
                         "load_avg_start": load_avg, "load_avg_end": _load()},
            "corpus": CORPUS.name, "rows": rows, "summary": summary(rows)}


def summary(rows: list) -> list:
    out = []
    for model in dict.fromkeys(r["model"] for r in rows):
        rs = [r for r in rows if r["model"] == model]
        quotes = sum(r["quotes_count"] for r in rs)
        found = sum(r["found"] for r in rs)
        tps = [r["tokens_per_s"] for r in rs if r["tokens_per_s"]]
        out.append({"model": model, "documents": len(rs),
                    "valid_json_pct": round(100 * sum(r["valid_json"] for r in rs) / len(rs)),
                    "quotes": quotes, "quotes_found": found,
                    "quote_accuracy_pct": round(100 * found / quotes) if quotes else 0,
                    "avg_seconds_per_doc": round(sum(r["seconds"] for r in rs) / len(rs), 1),
                    "avg_tokens_per_s": round(sum(tps) / len(tps), 1) if tps else None})
    return out


def markdown(summary_rows: list) -> str:
    lines = ["| Model | Docs | Valid JSON | Quotes found in source | Avg s/doc | Output tok/s |",
             "|---|---|---|---|---|---|"]
    for s in summary_rows:
        lines.append(f"| {s['model']} | {s['documents']} | {s['valid_json_pct']}% | {s['quotes_found']}/{s['quotes']} "
                     f"({s['quote_accuracy_pct']}%) | {s['avg_seconds_per_doc']} | {s['avg_tokens_per_s']} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--backend", choices=["ollama", "openai", *PROVIDERS], default="ollama")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--api-key-env", default="BENCH_API_KEY")
    ap.add_argument("--limit", type=int, default=0, help="only the first N documents")
    ap.add_argument("--mode", choices=["short", "long"], default="short")
    a = ap.parse_args()
    if a.backend in PROVIDERS:
        base, key_env = PROVIDERS[a.backend]
        a.base_url = a.base_url or base
        a.api_key_env = key_env if a.api_key_env == "BENCH_API_KEY" else a.api_key_env
    res = run(a.models, "ollama" if a.backend == "ollama" else "openai", a.base_url, a.api_key_env, a.limit, a.mode)
    res["provider"] = a.backend
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{a.backend}_{a.mode}.json"
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + markdown(res["summary"]) + f"\n\nsaved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
