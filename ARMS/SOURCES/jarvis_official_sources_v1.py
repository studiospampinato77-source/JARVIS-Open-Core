"""JARVIS official sources — Italian law articles from Normattiva (public, official).

Downloads the OFFICIAL text of a law article from normattiva.it, optionally the
version in force at a past date (e.g. the old bankruptcy law for procedures
opened before 15/07/2022). Results are cached locally with the source URL.

Only public legislation: no case files, no personal data.
Every result is support material, not legal advice (BOZZA_DA_VERIFICARE).
Usage:  python3 jarvis_official_sources_v1.py cc 2086
        python3 jarvis_official_sources_v1.py lf 5 2021-06-10
"""
from __future__ import annotations

from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
import hashlib
import html
import json
import os
import re
import sys
import urllib.request

BASE = "https://www.normattiva.it"
CACHE = Path(os.getenv("JARVIS_DATA_DIR", "data")) / "official_sources_cache"

# Most used acts (Normattiva URNs); any full URN works too.
ATTI = {
    "cc": ("Codice civile", "urn:nir:stato:regio.decreto:1942-03-16;262:2"),
    "cpc": ("Codice di procedura civile", "urn:nir:stato:regio.decreto:1940-10-28;1443:1"),
    "lf": ("Legge fallimentare (R.D. 267/1942)", "urn:nir:stato:regio.decreto:1942-03-16;267"),
    "ccii": ("Codice della crisi d'impresa e dell'insolvenza (D.Lgs. 14/2019)", "urn:nir:stato:decreto.legislativo:2019-01-12;14"),
    "tub": ("Testo unico bancario (D.Lgs. 385/1993)", "urn:nir:stato:decreto.legislativo:1993-09-01;385"),
}

UA = {"User-Agent": "Mozilla/5.0 (JARVIS Open Core; official sources reader)"}


def _testo(raw: str) -> str:
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S)
    raw = re.sub(r"<!--.*?-->", " ", raw, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def _scarica(opener, url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with opener.open(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def articolo(atto: str, numero: str, vigente_al: str | None = None) -> dict:
    """Testo ufficiale di un articolo. `atto` è una chiave di ATTI o un URN completo."""
    atto_key = atto.lower()
    nome, urn = ATTI.get(atto_key, (atto, atto))
    numero = str(numero).strip().lower().replace(" ", "")
    url_urn = f"{BASE}/uri-res/N2Ls?{urn}~art{numero}" + (f"!vig={vigente_al}" if vigente_al else "")

    chiave = hashlib.sha256(url_urn.encode()).hexdigest()[:24]
    cache_file = CACHE / f"{chiave}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    pagina = _scarica(opener, url_urn)

    # Normattiva carica il singolo articolo da un indirizzo interno: lo cerchiamo nella pagina.
    num_id = re.match(r"\d+", numero)
    link = None
    if num_id:
        for m in re.finditer(r"caricaArticolo\?[^\"' ]+", html.unescape(pagina)):
            if f"art.idArticolo={num_id.group(0)}&" in m.group(0):
                link = m.group(0)
                break
    testo = ""
    if link:
        testo = _testo(_scarica(opener, f"{BASE}/atto/{link}"))
    if not testo:
        testo = _testo(pagina)

    inizio = (re.search(r"Art\. ?" + re.escape(numero) + r"\b", testo)
              or re.search(r"Art\. ?" + re.escape(numero) + r"\b", testo, flags=re.I))
    if inizio:
        testo = testo[inizio.start():]
    testo = testo.split(" articolo precedente")[0].strip()

    trovato = bool(inizio) and len(testo) > 20
    risultato = {
        "fonte": "Normattiva (normattiva.it) - fonte ufficiale",
        "atto": nome,
        "articolo": numero,
        "vigente_al": vigente_al or "oggi",
        "url": url_urn,
        "testo": testo[:8000] if trovato else "",
        "stato": "TESTO_UFFICIALE_SCARICATO" if trovato else "TESTO_NON_TROVATO",
        "avvertenza": "BOZZA_DA_VERIFICARE: not legal advice; always check the version in force with a lawyer.",
        "scaricato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if trovato:
        CACHE.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(risultato, ensure_ascii=False, indent=2), encoding="utf-8")
    return risultato


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    r = articolo(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    print(json.dumps(r, ensure_ascii=False, indent=2))
