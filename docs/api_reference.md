# API Reference — RDTII 2.1 Compliance Engine

Base URL: `http://localhost:8000`
API Prefix: `/api/v1`

---

## Health

### `GET /health`

Returns liveness status of the API, database, and Redis.

**Response `200`:**
```json
{
  "status": "ok",
  "database": "ok",
  "redis": "ok",
  "version": "4.0.0",
  "timestamp": "2026-06-08T07:00:00Z"
}
```

---

## Analysis Runs

### `POST /api/v1/analysis/run`

Submit a new RDTII analysis job. Returns a `run_id` to poll.

**Request Body:**
```json
{
  "country": "Malaysia",
  "pillar_ids": [6, 7],
  "pdf_url": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `country` | string | ✅ | Must be: Malaysia \| Singapore \| Australia |
| `pillar_ids` | list[int] | ❌ | Specific pillars (1–12). Omit for all 12. |
| `pdf_url` | string | ❌ | Direct PDF URL to force-include as source |

**Response `202`:**
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "QUEUED",
  "message": "Analysis job queued for Malaysia. Poll /analysis/550e... for status."
}
```

---

### `GET /api/v1/analysis/runs`

List all analysis runs (newest first).

**Query Params:** `?limit=20&offset=0`

**Response `200`:** Array of run summaries.
```json
[
  {
    "id": "550e8400-...",
    "country": "Malaysia",
    "status": "COMPLETE",
    "created_at": "2026-06-08T07:00:00Z",
    "completed_at": "2026-06-08T07:45:00Z",
    "total_indicators": 10,
    "complete_indicators": 10
  }
]
```

**Run statuses:** `QUEUED` | `DISCOVERING` | `ANALYSING` | `COMPLETE` | `FAILED`

---

### `GET /api/v1/analysis/{run_id}`

Get full results for a run including all indicator results and discovered documents.

**Response `200`:**
```json
{
  "id": "550e8400-...",
  "country": "Malaysia",
  "status": "COMPLETE",
  "indicator_results": [
    {
      "id": 1,
      "pillar_id": 6,
      "indicator_id": "6.1",
      "raw_score": 0.5,
      "act_and_practice": "Personal Data Protection Act 2010, Section 129",
      "coverage": "Horizontal",
      "impact_comments": "Cross-border transfer of personal data is restricted...",
      "timeframe": "Since 15 November 2013",
      "references": "https://agc.gov.my/...",
      "note": "—",
      "confidence": 0.88,
      "verbatim_quote": "No personal data shall be transferred...",
      "article_citation": "PDPA 2010, s. 129",
      "prosecution_score": 0.5,
      "defense_score": 0.5,
      "arbiter_score": 0.5,
      "not_found": false,
      "discovery_tag": "NEW",
      "source_pdf_path": null,
      "location_ref": null,
      "processing_time": 4.23,
      "mapping_rationale": "Section 129 restricts cross-border transfer..."
    }
  ],
  "discovered_documents": [...]
}
```

**Response `404`:** Run not found.

---

### `GET /api/v1/analysis/{run_id}/export`

Export results as JSON, CSV, or Excel. Five format options available.

**Query Params:** `?format=json` | `?format=csv` | `?format=rdtii_flat_csv` | `?format=submission_csv` | `?format=excel`

| Format | Content-Type | Notes |
|---|---|---|
| `json` | `application/json` | Full data including audit fields |
| `csv` | `text/csv` | Official RDTII template — 13 cols with pillar header rows, split reference URLs |
| `rdtii_flat_csv` | `text/csv` | Legacy 9-column RDTII schema (`§2.1`), UTF-8 BOM |
| `submission_csv` | `text/csv` | Hackathon submission spec columns (`§17`): Economy, Law Name, Law Number/Ref, Last Amended, Article/Section, Discovery Tag, Location Ref, Verbatim Snippet, Mapping Rationale, Source URL, Confidence, Notes |
| `excel` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | 3 sheets: RDTII_Template + RDTII_9col + Submission, colour-coded scores, frozen header |

**Response `409`:** Run not yet complete.

---

### `GET /api/v1/analysis/results/all`

List all indicator results across all runs (newest first).

**Query Params:** `?limit=200&offset=0` (max limit: 5000)

**Response `200`:** Array of indicator result objects with run metadata.

```json
[
  {
    "id": 1,
    "run_id": "550e8400-...",
    "country": "Malaysia",
    "pillar_id": 6,
    "indicator_id": "6.1",
    "raw_score": 0.5,
    "act_and_practice": "Personal Data Protection Act 2010",
    "coverage": "Horizontal",
    "impact_comments": "...",
    "timeframe": "Since 2013",
    "references": "https://...",
    "note": "—",
    "confidence": 0.88,
    "verbatim_quote": "...",
    "article_citation": "s. 129",
    "discovery_tag": "NEW",
    "location_ref": "",
    "mapping_rationale": "...",
    "created_at": "2026-06-28T00:02:15"
  }
]
```

---

### `GET /api/v1/analysis/export/all`

Export all indicator results across all runs. Same format options as per-run export.

**Query Params:** `?format=json` | `?format=csv` | `?format=rdtii_flat_csv` | `?format=submission_csv` | `?format=excel`

| Format | Content-Type | Filename |
|---|---|---|
| `json` | `application/json` | `RDTII_all_results.json` |
| `csv` | `text/csv` | `RDTII_all_results_template.csv` |
| `rdtii_flat_csv` | `text/csv` | `RDTII_all_results_9col.csv` |
| `submission_csv` | `text/csv` | `RDTII_all_results_submission.csv` |
| `excel` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | `RDTII_all_results.xlsx` |

**Note:** Unlike per-run export, this endpoint does not require a completed run — it returns all persisted results regardless of run status.

---

### `GET /api/v1/analysis/audit/{result_id}`

### `GET /api/v1/analysis/audit/{result_id}`

Side-by-side audit view for a single indicator result. Returns AI extraction alongside source document metadata.

**Response `200`:**
```json
{
  "result_id": 42,
  "run_id": "550e...",
  "country": "Malaysia",
  "indicator_id": "6.1",
  "pillar_id": 6,
  "raw_score": 0.5,
  "act_and_practice": "PDPA 2010, Section 129",
  "impact_comments": "...",
  "verbatim_quote": "No personal data shall be transferred...",
  "article_citation": "s. 129",
  "references": "https://agc.gov.my/...",
  "confidence": 0.88,
  "not_found": false,
  "source_documents": [
    {
      "url": "https://agc.gov.my/pdpa.pdf",
      "source_type": "PRIMARY_HIGH",
      "language": "en",
      "ocr_quality_cer": 0.0,
      "download_status": "SUCCESS"
    }
  ]
}
```

---

### `GET /api/v1/analysis/review/queue`

Human-review queue — returns indicator results flagged by the Arbiter (confidence below threshold, or prosecution/defense disagreement).

**Query Params:** `?limit=50`

**Response `200`:**
```json
[
  {
    "run_id": "550e...",
    "country": "Malaysia",
    "indicator_id": "6.4",
    "pillar_id": 6,
    "raw_score": 0.5,
    "confidence": 0.35,
    "not_found": false,
    "prosecution_score": 0.5,
    "defense_score": 0.0,
    "verbatim_quote": "...",
    "article_citation": "s. 26",
    "impact_comments": "...",
    "reason": "Confidence below threshold"
  }
]
```

---

### `DELETE /api/v1/analysis/{run_id}`

Delete an analysis run and all related indicator results and documents.

**Response `204`:** No content.

---

## Real-Time Events

### `GET /api/v1/analysis/{run_id}/events`

Get paginated pipeline events for a run (newest first). Poll this while a run is in progress to see what the system is doing.

**Query Params:** `?offset=0&limit=50`

**Response `200`:**
```json
{
  "events": [
    {
      "id": 1,
      "event_type": "SEARCH_QUERY",
      "agent": "discovery",
      "indicator_id": "6.1",
      "message": "Generated 11 queries for 6.1",
      "data": null,
      "created_at": "2026-06-13T10:00:00Z"
    },
    {
      "id": 2,
      "event_type": "SEARCH_RESULT",
      "agent": "discovery",
      "indicator_id": "6.1",
      "message": "Found 14 unique URLs for 6.1",
      "data": "{\"total_results\": 14}",
      "created_at": "2026-06-13T10:00:05Z"
    },
    {
      "id": 3,
      "event_type": "CLASSIFY",
      "agent": "discovery",
      "indicator_id": "6.1",
      "message": "Classified as PRIMARY_HIGH: https://sso.agc.gov.sg/...",
      "data": "{\"source_type\": \"PRIMARY_HIGH\", \"url\": \"...\"}",
      "created_at": "2026-06-13T10:00:06Z"
    }
  ],
  "next_offset": 3,
  "has_more": false
}
```

| Field | Type | Description |
|---|---|---|
| `event_type` | string | `SEARCH_QUERY` \| `SEARCH_RESULT` \| `CLASSIFY` \| `DOWNLOAD` \| `DOWNLOAD_SUCCESS` \| `DOWNLOAD_FAILED` \| `ZONE1` \| `CHUNK` \| `EMBED` \| `PROSECUTION_START` \| `PROSECUTION_DONE` \| `DEFENSE_START` \| `DEFENSE_DONE` \| `ARBITER_START` \| `ARBITER_DONE` \| `INDICATOR_DONE` \| `STATUS` \| `ERROR` |
| `agent` | string | `discovery` \| `prosecution` \| `defense` \| `arbiter` |
| `indicator_id` | string | Indicator being processed (e.g. `6.1`, `7.4`) |
| `message` | string | Human-readable description |
| `data` | string | Optional JSON payload with structured details |

---

### `GET /api/v1/analysis/{run_id}/stream`

**Server-Sent Events (SSE)** — opens a persistent connection that pushes new events as they happen. No polling needed.

```bash
curl -N http://localhost:8000/api/v1/analysis/<run_id>/stream
```

Each event is a JSON payload:

```
event: PROSECUTION_DONE
data: {"id": 42, "event_type": "PROSECUTION_DONE", "agent": "prosecution", "indicator_id": "6.1", "message": "Prosecution score=0.5 confidence=0.8", "data": "{\"score\": 0.5, ...}", "created_at": "2026-06-13T10:01:00Z"}

event: DEFENSE_START
data: {"id": 43, ...}
```

| Event name | When it fires |
|---|---|
| `SEARCH_QUERY` | Queries generated per indicator |
| `SEARCH_RESULT` | Search results returned |
| `CLASSIFY` | URL classified (PRIMARY / SECONDARY / EXCLUDED) |
| `DOWNLOAD` | Download started |
| `DOWNLOAD_SUCCESS` | Download completed with text length |
| `DOWNLOAD_FAILED` | Download failed with error |
| `ZONE1` | Zone 1 validation result (PASS/FAIL) |
| `CHUNK` | Documents chunked |
| `EMBED` | Chunks embedded into vector DB |
| `PROSECUTION_START` / `PROSECUTION_DONE` | Prosecution agent — includes proposed score, quote, citation, confidence |
| `DEFENSE_START` / `DEFENSE_DONE` | Defense agent — includes exception_found, adjusted_score |
| `ARBITER_START` / `ARBITER_DONE` | Arbiter agent — includes final_score, not_found |
| `INDICATOR_DONE` | Full 3-agent pipeline complete for one indicator |
| `STATUS` | Pipeline phase transitions (DISCOVERING → ANALYSING → COMPLETE / FAILED) |

Heartbeat events (`event: heartbeat`) are sent every 0.5 seconds when no new events are available to keep the connection alive.

---

## Score Reference (RDTII 2.1 §5)

A higher score = **more restriction** = higher compliance cost.

| Score | Meaning |
|---|---|
| `1.0` | Full restriction / ban |
| `0.5` | Partial restriction / sectoral |
| `0.0` | No restriction found |

**Inverted indicators** (absence of framework = higher score): `7.1`, `7.2`, `8.1`, `8.2`, `9.1`, `12.9`

If no evidence is found: `not_found: true`, `raw_score: 0.0`

---

## Error Responses

```json
{ "detail": "Run 550e... not found." }      // 404
{ "detail": "Run not yet complete." }        // 409
{ "detail": "Country must be one of: ..." } // 422
```
