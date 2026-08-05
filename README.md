# RDTII 2.1 Compliance Engine 
AI-powered Digital Trade Regulatory Analysis  
Version 4.0.0 | Last updated: 2026-07-19

---

## What This Tool Does

Automates the UN Regional Digital Trade Integration Index (RDTII) regulatory analysis pipeline.

**Module 1 — Automated Evidence Discovery**  
Given an economy and regulatory topic, crawls official government legal portals (`sso.agc.gov.sg`, `agc.gov.my`, `legislation.gov.au`), retrieves relevant legislation (including scanned PDFs via OCR), and extracts structured text.

**Module 2 — Multi-Agent Adversarial Mapping**  
Runs a 3-agent LLM pipeline (Prosecution → Defense → Arbiter) per RDTII indicator. Extracted text is mapped to specific indicator IDs with article-level citations, verbatim snippets, and Discovery Tags (NEW / KNOWN).

**Module 3 — Persistence & Export**  
Scores are persisted in PostgreSQL and exported as JSON, CSV (3 variants), or Excel (3 sheets) in the official RDTII template format.

**Scope:** All 12 pillars (61 indicators), mandated coverage for Pillar 6 (Cross-border Data Flows) and Pillar 7 (Domestic Data Protection)  
**Economies:** Singapore, Malaysia, Australia

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/armmoon4/RDTII-2.1-Compliance-Engine.git
cd RDTII-2.1-Compliance-Engine
```

### 2. One-Command Docker

```bash
cp .env.example .env
# Edit .env — set at least one LLM API key and TAVILY_API_KEY
docker-compose up --build
```

| Service | URL |
|---|---|
| FastAPI (Swagger) | http://localhost:8000/docs |
| Health Check | http://localhost:8000/health |
| Streamlit Dashboard | http://localhost:8501 |
| Celery Flower | http://localhost:5555 |

### 3. Submit an Analysis

```bash
curl -X POST http://localhost:8000/api/v1/analysis/run \
  -H "Content-Type: application/json" \
  -d '{"country": "Singapore", "pillar_ids": [6, 7]}'
```

Poll status at `http://localhost:8000/api/v1/analysis/{run_id}` and export results at `http://localhost:8000/api/v1/analysis/{run_id}/export?format=json`.

---

## Full Usage

### API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/analysis/run` | Submit analysis job |
| `GET` | `/api/v1/analysis/{run_id}` | Poll status + results |
| `GET` | `/api/v1/analysis/{run_id}/export` | Export (json/csv/rdtii_flat_csv/submission_csv/excel) |
| `GET` | `/api/v1/analysis/{run_id}/stream` | SSE real-time event stream |
| `GET` | `/api/v1/analysis/{run_id}/events` | Paginated event log |
| `GET` | `/api/v1/analysis/results/all` | All results across runs |
| `GET` | `/api/v1/analysis/results/{country}` | Latest completion for country |
| `GET` | `/api/v1/analysis/indicators` | List all 61 indicators |
| `GET` | `/api/v1/analysis/countries` | Distinct analysed countries |
| `GET` | `/api/v1/analysis/runs` | Paginated run history |
| `GET` | `/api/v1/analysis/review/queue` | Low-confidence items for human review |
| `GET` | `/api/v1/analysis/audit/{result_id}` | Side-by-side audit view |
| `DELETE` | `/api/v1/analysis/{run_id}` | Delete run + related data |

### Submit with Options

```bash
curl -X POST http://localhost:8000/api/v1/analysis/run \
  -H "Content-Type: application/json" \
  -d '{
    "country": "Malaysia",
    "pillar_ids": [6, 7],
    "indicator_ids": ["6.1", "6.2", "7.1"],
    "llm_provider": "minimax",
    "pdf_url": "https://agc.gov.my/act709.pdf"
  }'
```

### Export Formats

```bash
# JSON (full audit trail)
curl "http://localhost:8000/api/v1/analysis/{run_id}/export?format=json"

# CSV — RDTII template (pillar header rows, split ref columns)
curl "http://localhost:8000/api/v1/analysis/{run_id}/export?format=csv"

# CSV — Flat 9-column (§2.1)
curl "http://localhost:8000/api/v1/analysis/{run_id}/export?format=rdtii_flat_csv"

# CSV —  spec (§17 — 13 columns)
curl "http://localhost:8000/api/v1/analysis/{run_id}/export?format=submission_csv"

# Excel (3 sheets: RDTII_Template, RDTII_9col, Submission)
curl "http://localhost:8000/api/v1/analysis/{run_id}/export?format=excel"
```

---

## Architecture Overview

```
Country + Pillar Input
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  MODULE 1 — Document Discovery Engine                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐            │
│  │ QueryGen  │→│ WebSearch │→│ URL Classifier│            │
│  └──────────┘  └──────────┘  └──────────────┘            │
│       → Zone1 Validator → Document Downloader             │
│       → Language Processor → Language Detection/Translate │
└─────────────────────┬─────────────────────────────────────┘
                      │ Validated DiscoveredDocuments
                      ▼
┌───────────────────────────────────────────────────────────┐
│  MODULE 2 — Multi-Agent Adversarial Analysis              │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐    │
│  │ Chunker  │→│ Embedder │→│ ChromaDB Vector Store │    │
│  └──────────┘  └──────────┘  └──────────────────────┘    │
│  Per indicator (parallel, max 5):                         │
│  ┌─────────────┐  ┌─────────┐  ┌──────────┐             │
│  │ Prosecution │→│ Defense │→│ Arbiter  │             │
│  │ Agent       │  │ Agent   │  │ Agent    │             │
│  └─────────────┘  └─────────┘  └──────────┘             │
│  ↕ Hallucination Validation → Score Snapping              │
│  ↕ Legal Knowledge Graph (supersession)                   │
│  ↕ Indicator Rule Enforcement (programmatic override)     │
└─────────────────────┬─────────────────────────────────────┘
                      │ IndicatorResult dicts
                      ▼
┌───────────────────────────────────────────────────────────┐
│  MODULE 3 — Output & Persistence                          │
│  ResultPersister (PostgreSQL) → FastAPI REST               │
│  → JSON / CSV (3 variants) / Excel (3 sheets)             │
└───────────────────────────────────────────────────────────┘
```

### Key Modules

| Module | File | Description |
|---|---|---|
| Query Generator | `app/modules/discovery/query_generator.py` | 7-template formula per indicator, LLM-enhanced |
| Web Searcher | `app/modules/discovery/web_searcher.py` | Tavily → DuckDuckGo → Bing → DDG Lite |
| URL Classifier | `app/modules/discovery/url_classifier.py` | Zone 1 routing (PRIMARY / SECONDARY / EXCLUDED) |
| Document Downloader | `app/modules/discovery/document_downloader.py` | httpx + Playwright, 4 PDF engines + OCR |
| Zone 1 Validator | `app/modules/discovery/zone1_validator.py` | Draft/repeal/future-date enforcement |
| Sample Kit Checker | `app/modules/discovery/sample_kit_checker.py` | CSV reference DB for KNOWN vs NEW tagging |
| Document Chunker | `app/modules/analysis/document_chunker.py` | Section-aware chunking (RecursiveCharacterTextSplitter) |
| Embedder | `app/modules/analysis/embeddings.py` | ChromaDB + BAAI/bge-base-en-v1.5 |
| Prosecution Agent | `app/modules/analysis/agents/prosecution_agent.py` | Finds strongest restrictive evidence |
| Defense Agent | `app/modules/analysis/agents/defense_agent.py` | Finds exceptions/exemptions |
| Arbiter Agent | `app/modules/analysis/agents/arbiter_agent.py` | Reconciliation + 9-column RDTII output + multi-law expansion |
| AI Client | `app/modules/analysis/agents/ai_client.py` | 8-provider abstraction with auto-fallback |
| Scoring Engine | `app/modules/analysis/scoring_engine.py` | Hardcoded VALID_SCORES + SCORE_CRITERIA, programmatic score mapping |
| Indicator Mapper | `app/modules/analysis/indicator_mapper.py` | Semantic warnings + rule enforcement |
| Legal Knowledge Graph | `app/modules/analysis/knowledge_graph.py` | NetworkX directed graph for supersession tracking |
| Result Persister | `app/modules/output/result_persister.py` | Saves IndicatorResult ORM rows |
| Exporters | `app/modules/output/exporters.py` | JSON, CSV (3 variants), Excel (3 sheets) |

---

## Swapping the LLM

The engine supports **8 providers** with automatic fallback. Set via `.env` or the `llm_provider` field in the API request.

### Auto Fallback Chain (default)

```
LLM_PROVIDER=auto
```

Priority: TokenRouter → MiniMax-M3 (Free) → Nvidia Nemotron (Free) → Grok (xAI) → DeepSeek → OpenAI → Gemini → Ollama

### Manual Provider Selection

Set in `.env`:

```ini
# Google Gemini
LLM_PROVIDER=gemini
GOOGLE_API_KEY=AIzaSy...

# OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Grok (xAI)
LLM_PROVIDER=grok
XAI_API_KEY=xai-...

# DeepSeek
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...

# MiniMax-M3 (Free via TokenRouter)
LLM_PROVIDER=minimax
TOKENROUTER_API_KEY=sk-...

# Nvidia Nemotron (Free via TokenRouter)
LLM_PROVIDER=nvidia
TOKENROUTER_API_KEY=sk-...

# Ollama (local, air-gapped)
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

No code changes needed — the LLM interface is abstracted in `app/modules/analysis/agents/ai_client.py`.

### Gemini → Ollama Automatic Fallback

If `GOOGLE_API_KEY` is set but Gemini fails (network, quota), falls back to Ollama automatically.

---

## Swapping the OCR Engine

| Engine | Library | Config | Notes |
|---|---|---|---|
| Tesseract | `pytesseract` | Built-in | Free, open-source; used for scanned PDFs via `pdf2image` |
| (Extensible) | — | — | Add new engine in `document_downloader.py` |

The OCR pipeline uses `pytesseract` with `pdf2image` (Poppler) for scanned/image-only PDFs. For machine-readable PDFs, it uses multi-engine extraction: pdfplumber → PyMuPDF → pdfminer.six → pypdf.

---

## Local Development (Without Docker)

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Tesseract OCR + Poppler (for scanned PDFs)

### Setup

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium --with-deps
python -m spacy download en_core_web_sm
cp .env.example .env
# Configure LLM provider + search keys
```

### Run Services

```bash
# Terminal 1: FastAPI
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Celery Worker
celery -A app.workers.celery_app worker --loglevel=info --concurrency=1

# Terminal 3: Streamlit (optional)
streamlit run streamlit_app.py --server.port=8501
```

---

## Supported Economies & Portals

| Economy | ISO | Legal System | Primary Portal | Regulator | Language |
|---|---|---|---|---|---|
| Singapore | SG | Common | sso.agc.gov.sg | PDPC | English |
| Malaysia | MY | Common | agc.gov.my | PDP Commissioner | English / Malay |
| Australia | AU | Common | legislation.gov.au | OAIC | English |

Full configuration in `countries_config.yaml`.

---

## Output Format


| # | Column | Description |
|---|---|---|
| 1 | economy | Official UN country name |
| 2 | law_name | Full official statute name |
| 3 | law_number_ref | Official act/law number (e.g. Act 709, Act 26 of 2012) |
| 4 | last_amended | Year of most recent amendment |
| 5 | indicator_id | RDTII code (e.g. P6-I1, P7-I3) |
| 6 | article_section | Exact article and paragraph (e.g. Art. 26(2), s. 129) |
| 7 | discovery_tag | NEW = independent find; KNOWN = sample kit |
| 8 | location_ref | PDF page number or URL anchor |
| 9 | verbatim_snippet | Exact quoted text — no paraphrasing |
| 10 | mapping_rationale | Why this provision maps to this indicator (max 300 chars) |
| 11 | source_url | Direct URL to law on official government portal |
| 12 | confidence | Model certainty score (0.00–1.00) |
| 13 | notes | OCR issues, partial doc, bilingual sources, cross-references |

Export via: `?format=submission_csv` or `?format=excel` (Submission sheet)

---

## Hallucination Defense

The engine includes a two-layer validation system that invalidates results when LLM-generated quotes cannot be verified against source documents:

1. **Exact substring match** (strict)
2. **Normalized fuzzy match + word-overlap Jaccard similarity** (≥ 0.75 threshold)

If both fail, the result is marked `not_found=True` with score 0.0 and confidence 0.1. Reference URLs are also validated — hallucinated URLs are stripped. This is implemented in `app/modules/analysis/analysis_orchestrator.py:474-574`.

---

## Running the Test Suite

```bash
pytest tests/ -v
```

Key test files:

| Test file | What it tests |
|---|---|
| `tests/test_crawler.py` | Query generation, URL classification, Zone 1 validation, document download, language processing |
| `tests/test_analyzer.py` | Scoring engine, indicator mapper, AI client JSON parsing, prosecution agent, arbiter agent, exporters |

---

## Project Structure

```
UN_backend/
├── app/
│   ├── main.py                    # FastAPI app entry, CORS, router mounting
│   ├── config.py                  # Pydantic Settings (env/.env)
│   ├── database.py                # Async SQLAlchemy engine + session factory
│   ├── events.py                  # Sync DB event emitter for pipeline progress
│   ├── api/
│   │   ├── analysis.py            # All REST endpoints
│   │   └── health.py              # /health — concurrent DB/Redis/LLM checks
│   ├── schemas/
│   │   └── analysis.py            # Pydantic request/response models
│   ├── models/
│   │   ├── analysis_run.py        # ORM: AnalysisRun (state machine)
│   │   ├── indicator_result.py    # ORM: 9-column RDTII output
│   │   ├── discovered_document.py # ORM: Module 1 docs + Zone 1 status
│   │   └── run_event.py           # ORM: pipeline event log
│   ├── modules/
│   │   ├── discovery/             # Module 1: Document Discovery (9 files)
│   │   ├── analysis/              # Module 2: Multi-Agent Analysis (10 files)
│   │   │   └── agents/            # Prosecution / Defense / Arbiter + AI client
│   │   └── output/                # Module 3: Persistence & Export
│   └── workers/
│       ├── celery_app.py          # Celery app config (solo pool)
│       └── tasks.py               # run_full_pipeline — async-wrapped Celery task
├── tests/
│   ├── test_crawler.py            # Module 1 tests
│   └── test_analyzer.py           # Module 2 tests
├── docs/
│   ├── architecture.md            # Full architecture documentation
│   ├── api_reference.md           # API reference
│   └── ollama_setup.md            # Ollama setup guide
├── chroma_db/                     # Persistent ChromaDB storage
├── asset/                         # Reference CSV (Legal Inventory) + UN emblem
├── config.yaml                    # Runtime YAML config
├── countries_config.yaml          # Per-country portal registry
├── docker-compose.yml             # 6 services: db, redis, api, worker, flower, streamlit
├── Dockerfile                     # Python 3.11-bookworm + Playwright + spaCy
├── Dockerfile.streamlit           # Streamlit container
├── streamlit_app.py               # Streamlit audit dashboard
├── frontend.html                  # Embedded frontend served at GET /
├── RDTII_Output_SG_MY_AU.csv      # Sample output (Singapore, Malaysia, Australia)
├── test.json                      # Sample API test payload
└── requirements.txt               # All Python dependencies
```

---

## Token Usage & Cost Tracking

The engine tracks token consumption per run. View in the Streamlit dashboard under the "Token Burn" tab, or via the API:

```bash
curl "http://localhost:8000/api/v1/analysis/token-usage?limit=10"
```

Cost is estimated based on provider-specific pricing (zero for free providers: MiniMax-M3, Nvidia Nemotron, Ollama).

---

## Known Limitations

- **OCR limited to Tesseract:** Scanned PDF OCR uses Tesseract (free, open-source). Azure Document Intelligence and Mistral OCR are not currently integrated.
- **No JavaScript crawl for dynamic portals:** The crawler uses Playwright as fallback but does not fully handle heavy JS-rendered pages.
- **Bilingual documents:** Malay-language sections of Malaysian documents rely on `deep-translator` which may have accuracy gaps.
- **Delegated legislation:** The tool retrieves primary statutes but does not automatically follow cross-references to subordinate regulations.
- **Per-run ephemeral ChromaDB:** A new vector collection is created, populated, queried, and deleted for every run — no caching across runs.

---



---

## License

Apache 2.0 Open Source License

---
