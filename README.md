# JARVIS Open Core

**English** · [Italiano](#italiano)

Guard-rails for small AI agents that do real work for a one-person business: they read public data, judge how much a piece of evidence is worth, and **never act on the outside world without a human "yes"**.

This repository is the open part of JARVIS, an assistant that runs on a single CPU-only server (12 cores, no GPU, local model `qwen3:8b` via Ollama). JARVIS supports an Italian consultant who helps small businesses in financial difficulty. Business data, documents and credentials stay private; the reusable building blocks are published here.

## What is in it

| Module | What it does |
|---|---|
| `ARMS/RESEARCH/jarvis_ingestion_gateway_v5.py` | Single controlled entry for external data. Every record gets a source, an access class (public, login required, licence restricted…), a SHA-256 hash, retrieval vs. observation time, freshness and a quality score. Network is **off by default**; sources that need a login or a licence are refused. Duplicates and conflicting sources are kept and flagged, not silently merged. |
| `GOVERNANCE/ingestion_access_catalog_v5.json` | The catalogue of sources and their access classes (ISTAT, Eurostat, Copernicus, InfoCamere, local files…). |
| `ARMS/RESEARCH/jarvis_evidence_gold_gate_v5.py` | Decides how much a claim is worth (RAW → BRONZE → SILVER → GOLD → GOLD_PLUS). LLM output is always INFERENCE, never fact. Copies of the same content do not count as independent sources. Old data, missing provenance or contrary evidence block GOLD. |
| `ARMS/RESEARCH/jarvis_source_intelligence_v5.py`, `jarvis_experience_loop_v5.py` | Navigation router and learning loop used by the tests: the agent learns only from GOLD-verified outcomes (an HTTP 200 is a technical success, not a result). |
| `CORE/jarvis_strategy_layer_v1.py` | Turns an objective into a mission plan. `request_action()` is the only door to the outside: email, messages, publishing and payments stay **BLOCKED** until a human approves that exact content (approval is bound to a SHA-256 of the action, so editing the text after approval blocks it again). |
| `ARMS/WORLD/jarvis_world_core_v4_clienti.py` | Ranks Italian cities using public signals only: businesses on OpenStreetMap inside the municipal boundary, crisis news from the last 90 days, population. Output: HOT / MEDIA / BASSA and which research "antennas" to switch on. |

Everything uses the Python standard library only.

## Try it (one command)

```bash
python demo.py
```

The demo needs no network, no model and no keys. It:

1. runs the built-in test suites of the Evidence Gold Gate (8 tests) and the Ingestion Gateway (11 tests), and shows a login-only source being refused;
2. shows an email **blocked** without approval, **blocked again** when the text is edited after approval, and **ready** only with the approved content (the gate itself never sends anything);
3. scores 3 cities (Milano, Firenze, Catania) from a snapshot of public data in `examples/cities_sample.json`. Scores are relative to the cities compared, so with only 3 cities the gaps look large; the full run compares 24 cities.

The full WORLD run downloads live data (Overpass and Google News, about 40 s per city):

```bash
JARVIS_ROOT=./data/world JARVIS_CONTACT=you@example.org python ARMS/WORLD/jarvis_world_core_v4_clienti.py
```

Configuration is only through environment variables: `JARVIS_DATA_DIR` (where records are stored, default `./data`), `JARVIS_ROOT`, `JARVIS_CONTACT` (for the OpenStreetMap User-Agent), `OLLAMA_URL`, `JARVIS_MODEL`.

## What runs today

- These modules run every day in the private JARVIS on one CPU-only server, next to a local 8B model.
- The local model is the bottleneck: analysing a 200-page document takes hours on CPU, and the 8B model is often too weak for long Italian documents.

## What we would do with GPU compute

We want to measure, not promise:

1. **Benchmark open models bigger than `qwen3:8b`** (e.g. 14B–70B open-weight models) on **public** Italian documents (laws from Normattiva, public court decisions, public company news): speed (pages/minute), cost per document, and quality checked mechanically against the Evidence Gold Gate (how many quoted passages are actually found in the source document).
2. **Publish the numbers and the benchmark scripts** in this repository, so other small teams can choose a model with data instead of guesses.
3. Keep the same rule: the model writes drafts; the gateway, the gold gate and the human approval decide.

## Limits (honestly)

- This is not an autonomous agent and does not try to be one: every external action needs a human.
- PDF, OCR and Office readers, the web search adapters and the private business modules are not part of this repository; for those formats the gateway returns `READER_NOT_INCLUDED`.
- WORLD scores are a starting point for research, not a judgement on any city or company.

## License

MIT, see [LICENSE](LICENSE). OpenStreetMap data © OpenStreetMap contributors (ODbL).

---

<a id="italiano"></a>
## Italiano

Paletti di sicurezza per piccoli agenti di IA che fanno lavoro vero per un'attività di una sola persona: leggono dati pubblici, giudicano quanto vale una prova e **non agiscono mai all'esterno senza il "sì" di una persona**.

È la parte aperta di JARVIS, un assistente che gira su un solo server senza GPU (12 core, modello locale `qwen3:8b` con Ollama) e aiuta un consulente italiano che assiste piccole imprese in difficoltà. Dati, documenti e credenziali restano privati; qui ci sono i mattoni riutilizzabili.

### Cosa contiene
- **Ingestion gateway**: unica porta d'ingresso per i dati esterni. Ogni dato riceve fonte, classe di accesso, impronta SHA-256, data di raccolta e di osservazione, freschezza e qualità. Rete **spenta di base**; le fonti che richiedono login o licenza vengono rifiutate.
- **Evidence Gold Gate**: decide quanto vale un'affermazione (RAW → GOLD_PLUS). Quello che scrive un modello di IA è sempre "inferenza", mai un fatto. Copie dello stesso testo non contano come fonti indipendenti.
- **Strategy layer**: piano di missione; email, messaggi, pubblicazioni e pagamenti restano **BLOCCATI** finché una persona non approva quel contenuto preciso. Se il testo cambia dopo l'approvazione, torna bloccato.
- **WORLD core**: classifica le città italiane con soli dati pubblici (imprese su OpenStreetMap, notizie di crisi degli ultimi 90 giorni, popolazione).

### Come si prova
```bash
python demo.py
```
Non servono rete, modello né chiavi. Esegue i test interni (8 + 11), mostra un'email bloccata senza approvazione e il punteggio di 3 città con dati pubblici di esempio.

### Cosa faremmo con la GPU
Confrontare modelli aperti più grandi di `qwen3:8b` su documenti italiani **pubblici** (leggi, sentenze pubbliche, notizie sulle imprese) misurando velocità, costo per documento e qualità (quante citazioni si trovano davvero nel documento), e pubblicare numeri e script qui.

### Licenza
MIT. Dati OpenStreetMap © contributori OpenStreetMap (ODbL).
