# System Architecture — RDTII 2.1 Compliance Engine

## Overview

The system is a 3-module automated pipeline triggered via a Celery task from a FastAPI REST API.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER                                        │
│   REST Client / curl    →   FastAPI (port 8000)   →   Celery Task Queue     │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 │ POST /api/v1/analysis/run
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  MODULE 1 — Document Discovery Engine (app/modules/discovery/)               │
│                                                                              │
│  QueryGenerator                                                              │
│    Converts (country, indicator_id) → 7 ordered search queries               │
│    Uses hardcoded INDICATOR_QUESTION_BANK (61 indicators) +                  │
│    COUNTRY_PORTAL_REGISTRY (Malaysia, Singapore, Australia)                  │
│         │                                                                    │
│         ▼                                                                    │
│  WebSearcher (DuckDuckGo)                                                    │
│    Executes queries in priority order; early-stop if 2+ .gov results         │
│         │                                                                    │
│         ▼                                                                    │
│  URLClassifier                                                               │
│    PRIMARY_HIGH (known portal) | PRIMARY_GAZETTE | PRIMARY_MEDIUM (.gov)     │
│    SECONDARY_LEAD (skip download) | SECONDARY_APPROVED (UNCTAD/WB)           │
│    EXCLUDED (draft/consultation/future-dated)                                │
│         │                                                                    │
│         ▼                                                                    │
│  DocumentDownloader                                                          │
│    httpx (static HTML/PDF) → Playwright fallback (JS-rendered)               │
│    PDF text: pdfminer.six → pypdf fallback                                   │
│         │                                                                    │
│         ▼                                                                    │
│  Zone1Validator                                                              │
│    Heuristic checks: draft patterns | repeal patterns | future effective date│
│         │                                                                    │
│         ▼                                                                    │
│  LanguageProcessor                                                           │
│    langdetect → GoogleTranslator (4000-char chunks)                          │
│         │                                                                    │
│         ▼                                                                    │
│  → DiscoveredDocument rows saved to PostgreSQL                               │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 │ list[DiscoveredDocument]
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  MODULE 2 — Multi-Agent Adversarial Analysis (app/modules/analysis/)         │
│                                                                              │
│  LegalSystemClassifier                                                       │
│    Civil | Common | Mixed → determines if case law is a valid source         │
│                                                                              │
│  DocumentChunker (LangChain RecursiveCharacterTextSplitter)                  │
│    Splits on Chapter/Article/Section boundaries, 3000-char chunks            │
│                                                                              │
│  Embeddings (sentence-transformers: all-MiniLM-L6-v2 + ChromaDB)            │
│    Stores per-run vector collection; cleaned up after analysis               │
│                                                                              │
│  LegalKnowledgeGraph (spaCy NER + NetworkX DiGraph)                         │
│    Nodes: Article/Section/Clause identifiers                                 │
│    Edges: cross_reference | supersedes                                       │
│                                                                              │
│  Per-Indicator Pipeline (for each of 50 RDTII indicators):                  │
│                                                                              │
│    ┌─────────────────────────────────────────────────────────────┐           │
│    │  ChromaDB top-K retrieval → keyword fallback                │           │
│    │         │                                                   │           │
│    │         ▼                                                   │           │
│    │  PROSECUTION AGENT                                          │           │
│    │    - Finds strongest evidence of restriction                │           │
│    │    - Outputs: quote, citation, proposed_score, confidence   │           │
│    │         │                                                   │           │
│    │         ▼                                                   │           │
│    │  DEFENSE AGENT                                              │           │
│    │    - Searches for exceptions, carve-outs, exemptions        │           │
│    │    - Outputs: exception_found, adjusted_score               │           │
│    │         │                                                   │           │
│    │         ▼                                                   │           │
│    │  ARBITER AGENT                                              │           │
│    │    - Reconciles prosecution vs. defense                     │           │
│    │    - Outputs: 9-column RDTII result                         │           │
│    └─────────────────────────────────────────────────────────────┘           │
│                                                                              │
│  ScoringEngine                                                               │
│    Validates/snaps AI score to nearest valid score per indicator             │
│    Valid score sets: hardcoded per RDTII 2.1 spec §5                         │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 │ list[dict] indicator results
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  MODULE 3 — Output & Persistence (app/modules/output/)                       │
│                                                                              │
│  ResultPersister                                                             │
│    Saves IndicatorResult rows to PostgreSQL (9-column RDTII schema)          │
│    Linked to AnalysisRun via run_id FK                                       │
│                                                                              │
│  Exporters                                                                   │
│    export_json() → structured JSON with audit fields                         │
│    export_csv()  → pandas DataFrame → UTF-8 CSV                              │
│    export_excel() → openpyxl with colour-coded scores (red/orange/green)     │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Database Schema

```
analysis_runs
  id (UUID PK) | country | status | pillar_ids_requested
  pdf_url | error_message | celery_task_id | created_at | completed_at

discovered_documents
  id (INT PK) | run_id (FK) | url | title | language
  source_type | enforcement_status | zone1_passed
  original_content | translated_content | content_hash
  download_status | indicator_id | search_query_used | created_at

indicator_results
  id (INT PK) | run_id (FK) | pillar_id | indicator_id
  raw_score | act_and_practice | coverage | impact_comments
  timeframe | references | note | confidence
  verbatim_quote | article_citation | not_found
  prosecution_score | defense_score | arbiter_score | created_at
```

## AI Provider Chain

```
GOOGLE_API_KEY set?
  YES → langchain-google-genai → Gemini 1.5 Flash
  NO  → langchain-ollama → Ollama (llama3.1 default)
```

## Technology Stack

| Component | Technology |
|---|---|
| API | FastAPI 0.111 + uvicorn |
| Task Queue | Celery 5.3 + Redis 7 |
| Database | PostgreSQL 16 + SQLAlchemy 2 (async) |
| Vector Store | ChromaDB 0.5 + sentence-transformers |
| Web Search | DuckDuckGo Search (no API key) |
| PDF Parsing | pdfminer.six + pypdf |
| JS Rendering | Playwright (Chromium) |
| NLP | spaCy en_core_web_sm |
| Knowledge Graph | NetworkX DiGraph |
| LLM (primary) | Google Gemini 1.5 Flash |
| LLM (fallback) | Ollama llama3.1 (local) |
| Translation | deep-translator (Google) |
| Export | pandas + openpyxl |
