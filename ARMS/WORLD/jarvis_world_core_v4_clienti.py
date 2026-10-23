"""JARVIS WORLD CORE V4 — DOVE SONO I CLIENTI / WHERE THE CLIENTS ARE.

Ranks Italian cities for SME-support outreach using only public, open signals.

Punteggio per città fatto di tre segnali reali e pubblici:
  - AZIENDE: uffici, artigiani e negozi censiti su OpenStreetMap (Overpass), dentro il confine del comune;
  - CRISI: articoli italiani degli ultimi 90 giorni su fallimenti, pignoramenti, crisi aziendali, cassa integrazione
    (Google News RSS; Google Trends e GDELT bloccano il server);
  - POPOLAZIONE: dal confine comunale OpenStreetMap, altrimenti dal GHSL ufficiale della v3.1.
Per ogni città indica le antenne da accendere (stessi nomi del piano v3.1). NON contatta nessuno, NON pubblica.
Lenta (Overpass ~40 s a città): pensata per girare di notte. I risultati per città restano in cache 7 giorni.

Uso:  JARVIS_ROOT=./data/world JARVIS_CONTACT=you@example.org python3 jarvis_world_core_v4_clienti.py
      (JARVIS_CONTACT goes in the User-Agent, as the OpenStreetMap/Overpass usage policy asks)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request

VERSION = "4.0.0"
ROOT = Path(os.getenv("JARVIS_ROOT", "data/world"))
DATA = ROOT / "data"
OUT = ROOT / "output"
CACHE = DATA / "world_core_cache_v4"
V31_LATEST = DATA / "jarvis_world_core_v3_1_latest.json"
UA = f"JARVIS-world/1.0 ({os.getenv('JARVIS_CONTACT', 'set JARVIS_CONTACT')})"

CITTA = {
    "Milano": "Lombardia", "Roma": "Lazio", "Torino": "Piemonte", "Bologna": "Emilia-Romagna",
    "Napoli": "Campania", "Firenze": "Toscana", "Palermo": "Sicilia", "Catania": "Sicilia",
    "Prato": "Toscana", "Pisa": "Toscana", "Livorno": "Toscana", "Arezzo": "Toscana", "Siena": "Toscana",
    "Lucca": "Toscana", "Pistoia": "Toscana", "Grosseto": "Toscana", "Massa": "Toscana",
    "Messina": "Sicilia", "Siracusa": "Sicilia", "Trapani": "Sicilia", "Agrigento": "Sicilia",
    "Ragusa": "Sicilia", "Caltanissetta": "Sicilia", "Enna": "Sicilia",
}
PAROLE_CRISI = ('(fallimento OR pignoramento OR "crisi aziendale" OR "cassa integrazione" OR licenziamenti '
                'OR "concordato preventivo" OR "liquidazione giudiziale")')
PESI = {"aziende": 0.45, "crisi": 0.35, "popolazione": 0.20}


def cache_leggi(nome: str, giorni: int = 7):
    p = CACHE / nome
    if p.exists() and datetime.now().timestamp() - p.stat().st_mtime < giorni * 86400:
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def cache_scrivi(nome: str, dati) -> None:
    (CACHE / nome).write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")


def overpass(citta: str) -> dict:
    """Attività (office/craft/shop) e popolazione del comune, dal confine amministrativo italiano (ref:ISTAT)."""
    q = (f'[out:json][timeout:170];area["name"="{citta}"]["admin_level"="8"]["boundary"="administrative"]["ref:ISTAT"]->.a;'
         '.a out tags;(nwr["office"](area.a);nwr["craft"](area.a);nwr["shop"](area.a););out count;')
    req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                                 data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=200) as r:
        el = json.load(r).get("elements", [])
    aree = [e for e in el if e.get("type") == "area"]
    conta = next((e for e in el if e.get("type") == "count"), {})
    pop = None
    if aree:
        try:
            pop = float(str(aree[0].get("tags", {}).get("population", "")).replace(".", "").replace(" ", ""))
        except ValueError:
            pop = None
    return {"aree_trovate": len(aree), "attivita": int(conta.get("tags", {}).get("total", 0) or 0), "pop_osm": pop}


def notizie_crisi(citta: str) -> int:
    q = urllib.parse.quote(f'"{citta}" {PAROLE_CRISI} when:90d')
    req = urllib.request.Request(f"https://news.google.com/rss/search?q={q}&hl=it&gl=IT&ceid=IT:it",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return len(re.findall(r"<item>", r.read().decode("utf-8", "ignore")))


def pop_ghsl() -> dict:
    if not V31_LATEST.exists():
        return {}
    d = json.loads(V31_LATEST.read_text(encoding="utf-8"))
    righe = d.get("cities") or d.get("results") or d.get("ranking") or []
    out = {}
    for r in righe if isinstance(righe, list) else []:
        nome = r.get("city") or r.get("name")
        g = r.get("ghsl") or {}
        if nome and g.get("population_metric"):
            out[nome] = float(g["population_metric"])
    return out


def norm_log(valori: list) -> list:
    ok = [v for v in valori if isinstance(v, (int, float)) and v > 0]
    if not ok:
        return [0.0] * len(valori)
    lo, hi = math.log1p(min(ok)), math.log1p(max(ok))
    return [0.0 if not (isinstance(v, (int, float)) and v > 0) else
            (100.0 if hi == lo else 100 * (math.log1p(v) - lo) / (hi - lo)) for v in valori]


def antenne(punti: float, pop: float | None) -> tuple[str, str, list]:
    if punti >= 70:
        livello, azione = "HOT", "ACCENDI_ANTENNE"
        a = ["CACCIATORE_CLIENTI", "OVERPASS_IMPRESE", "FINANZA_AGEVOLATA_CLIENTI", "CACCIATORE_IMPRESE_BANDI", "PUBBLICO_LIBRO"]
    elif punti >= 45:
        livello, azione = "MEDIA", "OSSERVA_SELETTIVAMENTE"
        a = ["OVERPASS_IMPRESE", "PUBBLICO_LIBRO"]
    else:
        return "BASSA", "NON_SPENDERE_RISORSE", []
    if pop and pop >= 300000:
        a.append("PUBBLICO_CONSUMER")
    return livello, azione, a


def punteggia(righe: list) -> list:
    """Score rows with keys attivita, notizie_crisi_90g, popolazione (log-normalised against each other)."""
    sa = norm_log([r.get("attivita") for r in righe])
    sc = norm_log([r.get("notizie_crisi_90g") for r in righe])
    sp = norm_log([r.get("popolazione") for r in righe])
    for r, a, c, p in zip(righe, sa, sc, sp):
        r["punteggi"] = {"aziende": round(a, 1), "crisi": round(c, 1), "popolazione": round(p, 1)}
        r["punteggio"] = round(PESI["aziende"] * a + PESI["crisi"] * c + PESI["popolazione"] * p, 1)
        r["livello"], r["azione"], r["antenne"] = antenne(r["punteggio"], r.get("popolazione"))
    righe.sort(key=lambda r: -r["punteggio"])
    return righe


def main() -> int:
    for p in (DATA, OUT, CACHE):
        p.mkdir(parents=True, exist_ok=True)
    ghsl = pop_ghsl()
    righe = []
    for i, (citta, regione) in enumerate(CITTA.items(), 1):
        nome_cache = f"{citta.lower()}.json"
        dati = cache_leggi(nome_cache)
        if dati is None:
            dati = {"citta": citta}
            try:
                dati.update(overpass(citta))
            except Exception as e:  # una città lenta non ferma le altre
                dati.update({"aree_trovate": 0, "attivita": None, "pop_osm": None, "errore_osm": str(e)[:120]})
            try:
                dati["notizie_crisi_90g"] = notizie_crisi(citta)
            except Exception as e:
                dati["notizie_crisi_90g"], dati["errore_news"] = None, str(e)[:120]
            if dati.get("attivita") is not None and dati.get("notizie_crisi_90g") is not None:
                cache_scrivi(nome_cache, dati)
            time.sleep(6)
        dati["regione"] = regione
        dati["popolazione"] = dati.get("pop_osm") or ghsl.get(citta)
        righe.append(dati)
        print(f"[{i:2}/{len(CITTA)}] {citta:<14} attività {dati.get('attivita')!s:>6} · notizie crisi {dati.get('notizie_crisi_90g')!s:>3} · pop {dati.get('popolazione')}", flush=True)

    punteggia(righe)

    adesso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    piano = {"version": VERSION, "generato": adesso, "fonti": ["OpenStreetMap/Overpass", "Google News RSS", "GHSL JRC (v3.1)"],
             "pesi": PESI, "citta": righe,
             "nota": "Solo analisi: nessun contatto, invio o pubblicazione. Le antenne si accendono solo dopo l'approvazione umana."}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (OUT / f"jarvis_world_core_v4_{stamp}.json").write_text(json.dumps(piano, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "world_core_action_plan_v4_latest.json").write_text(json.dumps(piano, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nCLASSIFICA WORLD V4 — DOVE SONO I CLIENTI")
    for n, r in enumerate(righe, 1):
        print(f"{n:2}. {r['citta']:<14} {r['regione']:<15} {r['punteggio']:5.1f} {r['livello']:<6} {', '.join(r['antenne']) or '-'}")
    print("\nPIANO:", DATA / "world_core_action_plan_v4_latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
