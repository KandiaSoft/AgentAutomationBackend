# AgentAutomaton — Backend

Automated testing harness for **preventivatore AI**, an Italian construction-sector quoting agent operated by Edilnet. The backend simulates synthetic human clients using Google Gemini, drives multi-turn conversations with the real agent REST API, persists every turn to SQLite, and streams live events to connected frontends over WebSocket.

---

## Table of Contents

1. [Architecture overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Running](#running)
6. [API reference](#api-reference)
7. [WebSocket protocol](#websocket-protocol)
8. [Database schema](#database-schema)
9. [Personas](#personas)
10. [Scenarios](#scenarios)
11. [Concurrency model](#concurrency-model)
12. [Retry and timeout behaviour](#retry-and-timeout-behaviour)
13. [Testing](#testing)
14. [Project structure](#project-structure)

---

## Architecture overview

```
┌─────────────────────────────────────────────────────┐
│                   FastAPI server                    │
│                                                     │
│  POST /api/simulations ──► SimulationManager        │
│                                  │                  │
│                         asyncio.create_task()       │
│                                  │                  │
│                         ClientSimulator.run()       │
│                         ┌────────────────────┐      │
│                         │ 1. resolve scenario │      │
│                         │ 2. client turn 1   │      │
│                         │ loop:              │      │
│                         │   agent_client     │──────┼──► preventivatore AI
│                         │   ↓ AgentResponse  │      │    (external HTTPS)
│                         │   gemini_client    │──────┼──► Google Gemini API
│                         │   ↓ next turn      │      │
│                         │   persist + WS     │      │
│                         └────────────────────┘      │
│                                  │                  │
│  GET /ws/simulations ────────────┘ broadcast        │
│                                                     │
│  SQLite (aiosqlite) ─ simulations.db                │
└─────────────────────────────────────────────────────┘
```

Each simulation runs as an independent `asyncio.Task` controlled by a `Semaphore(MAX_CONCURRENT)`. Up to 10 simulations may be active simultaneously; additional ones queue and start as slots become available.

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| [uv](https://docs.astral.sh/uv/) | latest |

---

## Installation

```bash
cd backend
uv sync                     # installs deps into .venv
cp .env.example .env        # then fill in your values
```

To install dev dependencies as well:

```bash
uv sync --extra dev
```

---

## Configuration

All settings are loaded by **pydantic-settings** from a `.env` file (or real environment variables). Keys are case-insensitive.

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | *(required)* | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model identifier |
| `AGENT_URL` | `https://test-agent-prev-ai-777.edilnet.it/invoke_agent` | Preventivatore AI endpoint |
| `AGENT_USER_ID` | `test-user-001` | `user_id` sent in every agent request |
| `AGENT_USERNAME` | `Test Client` | `username` sent in every agent request |
| `MAX_CONCURRENT` | `10` | Max simultaneous simulation tasks |
| `DB_PATH` | `simulations.db` | Path to SQLite file (relative to `backend/`) |
| `AGENT_TIMEOUT_CONNECT` | `10.0` | TCP connect timeout for agent calls (seconds) |
| `AGENT_TIMEOUT_READ` | `300.0` | Read timeout for agent calls (seconds) — set higher for slow responses |
| `AGENT_MAX_RETRIES` | `2` | Max retry attempts on `ReadTimeout` / `ConnectTimeout` |
| `DELAY_MIN_MS` | `2000` | Default minimum inter-turn delay (ms) |
| `DELAY_MAX_MS` | `6000` | Default maximum inter-turn delay (ms) |

### Example `.env`

```env
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.5-flash
AGENT_URL=https://test-agent-prev-ai-777.edilnet.it/invoke_agent
AGENT_USER_ID=test-user-001
AGENT_USERNAME=Test Client
MAX_CONCURRENT=10
DB_PATH=simulations.db
AGENT_TIMEOUT_READ=600.0
AGENT_MAX_RETRIES=2
```

---

## Running

```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

The server starts on `http://localhost:8000`. Interactive docs are at `http://localhost:8000/docs`.

Health check:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

## API reference

### POST `/api/simulations`

Start one or more simulations. Returns IDs immediately; simulations run asynchronously.

**Request body** (`SimulationConfig`):

```jsonc
{
  "persona_key": "homeowner_basic",   // required — see Personas section
  "language": "it",                   // "it" | "en" | "es"  (default "it")
  "count": 1,                         // 1–10 parallel simulations
  "delay_ms": [2000, 6000],           // [min, max] inter-turn delay in ms
  // ONE of the three scenario fields is required:
  "scenario_key": "bagno_completo",   // key from the catalog
  "scenario_text": "...",             // free-form text sent verbatim
  "generate_scenario": true           // ask Gemini to generate one
}
```

**Response** `200 OK`:

```json
{
  "simulation_ids": ["uuid1", "uuid2"]
}
```

**Errors**:
- `400` if no scenario source is provided.

---

### GET `/api/simulations`

List all simulations, most recent first.

**Query params**:
- `status` — filter by status: `pending` | `running` | `finished` | `error` | `stopped`

**Response**: array of `SimulationSummary` objects.

```jsonc
[
  {
    "id": "uuid",
    "thread_id": "uuid",
    "persona_key": "homeowner_basic",
    "scenario_key": "bagno_completo",
    "initial_request": "Rifacimento completo bagno...",
    "language": "it",
    "status": "finished",
    "finished": true,
    "total_in_tokens": 4200,
    "total_out_tokens": 980,
    "turn_count": 14,
    "created_at": "2026-05-30T10:00:00Z",
    "finished_at": "2026-05-30T10:04:30Z",
    "error": null,
    "short_codes": [...]
  }
]
```

---

### GET `/api/simulations/{id}`

Retrieve full detail for one simulation including all turns.

**Response**: `SimulationDetail` = `SimulationSummary` + `turns` array.

Each turn:

```jsonc
{
  "id": 42,
  "simulation_id": "uuid",
  "turn_index": 3,
  "role": "agent",            // "client" | "agent"
  "question": null,           // text sent by client (null for agent turns)
  "answer": "Per il bagno...",// agent's answer text (null for client turns)
  "understanding": "...",     // agent's internal understanding
  "is_questionnaire": true,   // agent sent a structured questionnaire
  "has_interrupt": false,
  "questionnaire": [...],     // array of {number, question, responses[]}
  "client_reasoning": null,   // Gemini's reasoning (client turns only)
  "in_tokens": 1200,
  "out_tokens": 340,
  "created_at": "2026-05-30T10:01:15Z"
}
```

---

### DELETE `/api/simulations/{id}`

Cancel an in-progress simulation (sets status → `stopped`). No-op if already terminal.

**Response**: `204 No Content`

---

### GET `/api/personas`

Returns the list of available client personas.

```json
[
  { "key": "homeowner_basic", "label": "Proprietario base", "description": "..." },
  ...
]
```

---

### GET `/api/scenarios`

Returns the scenario catalog.

```json
[
  { "key": "bagno_completo", "label": "Rifacimento completo bagno 8mq", "text": "...", "category": "bagno" },
  ...
]
```

---

## WebSocket protocol

Two endpoints — both send the same event envelope:

```jsonc
{
  "type": "turn" | "status" | "error" | "ping",
  "simulation_id": "uuid",
  "payload": { ... }
}
```

### `GET /ws/simulations`

Global stream — receives events for **all** simulations. Used by the dashboard to auto-refresh without polling.

### `GET /ws/simulations/{sim_id}`

Single-simulation stream — receives events only for the specified simulation. Used by the detail page.

### Keep-alive

If no event is emitted for 30 seconds, the server sends `{"type":"ping"}`. Clients should silently discard pings.

### Event payloads

**`turn`** — a new conversation turn is available:
```jsonc
{
  "turn_index": 5,
  "role": "agent",
  "answer": "...",
  "understanding": "...",
  "is_questionnaire": true,
  "has_interrupt": false,
  "questionnaire": [...],
  "in_tokens": 800,
  "out_tokens": 220
}
```

**`status`** — simulation lifecycle change:
```jsonc
{
  "status": "running" | "finished" | "error" | "stopped",
  "short_codes": [...],    // only on "finished"
  "error": "message"       // only on "error"
}
```

---

## Database schema

File: `simulations.db` (SQLite)

### `simulations`

| Column | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID |
| `thread_id` | TEXT | UUID sent to agent as conversation key |
| `persona_key` | TEXT | Persona used |
| `scenario_key` | TEXT | Catalog key (NULL if generated/custom) |
| `initial_request` | TEXT | Exact text sent as first client message |
| `language` | TEXT | `it` / `en` / `es` |
| `status` | TEXT | `pending` / `running` / `finished` / `error` / `stopped` |
| `finished` | INTEGER | 1 if conversation ended normally |
| `short_codes_json` | TEXT | JSON array of `ShortCodeGroup` objects |
| `total_in_tokens` | INTEGER | Cumulative Gemini input tokens |
| `total_out_tokens` | INTEGER | Cumulative Gemini output tokens |
| `delay_min_ms` | INTEGER | Min inter-turn delay |
| `delay_max_ms` | INTEGER | Max inter-turn delay |
| `created_at` | TEXT | ISO-8601 UTC |
| `finished_at` | TEXT | ISO-8601 UTC (NULL if not done) |
| `error` | TEXT | Error message (NULL on success) |

### `turns`

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `simulation_id` | TEXT FK | References `simulations(id)` CASCADE DELETE |
| `turn_index` | INTEGER | Sequential 0-based counter |
| `role` | TEXT | `client` or `agent` |
| `question` | TEXT | Text sent by client (NULL for agent turns) |
| `answer` | TEXT | Agent's answer text (NULL for client turns) |
| `understanding` | TEXT | Agent's internal reasoning field |
| `is_questionnaire` | INTEGER | 1 if agent sent a structured questionnaire |
| `has_interrupt` | INTEGER | 1 if turn requires client to set `interrupt=1` |
| `questionnaire_json` | TEXT | JSON — agent's question list with options |
| `client_reasoning` | TEXT | Gemini's explanation for its choice (client turns) |
| `in_tokens` | INTEGER | Gemini input tokens for this turn |
| `out_tokens` | INTEGER | Gemini output tokens for this turn |
| `created_at` | TEXT | ISO-8601 UTC |

### Migrations

`init_db()` runs on startup and applies forward-only `ALTER TABLE` migrations inside a try/except to handle existing databases safely. No down-migrations exist by design.

---

## Personas

Five built-in client personas. Each is a system prompt written in English (so Gemini interprets it correctly regardless of UI locale) plus a universal rule that mandates writing all client messages in the selected `language`.

| Key | Label | Behaviour |
|---|---|---|
| `homeowner_basic` | Proprietario base | No technical knowledge, 1–2 sentence answers |
| `homeowner_technical` | Proprietario tecnico | Uses correct construction terminology |
| `indecisive` | Indeciso | Sometimes asks for clarification, adds details mid-conversation |
| `terse` | Telegrafico | Bare minimum answers, always picks a numeric questionnaire option |
| `detail_oriented` | Dettagliato | Verbose, uses free-text questionnaire answer to add precision |

**Critical questionnaire rule** (enforced in all personas): when the agent sends a questionnaire, the client must copy the chosen option verbatim — including the numeric prefix `"N. testo"` — and **must not translate** it. This is required because the agent validates exact string matching on its end.

---

## Scenarios

Ten built-in scenarios in the `SCENARIOS` catalog, covering common Italian renovation work:

| Key | Category | Description |
|---|---|---|
| `bagno_completo` | bagno | Full bathroom renovation 8m² |
| `elettrico_bagno` | elettrico | Light switch + grounded outlet in bathroom |
| `piastrelle_bagno` | rivestimenti | Tile replacement 3×5m bathroom |
| `riscaldamento_pavimento` | impianti | Underfloor heating 100m² |
| `cartongesso` | muratura | Drywall partitions throughout apartment |
| `cucina_completa` | cucina | Full kitchen renovation 12m² |
| `tetto_coibentazione` | isolamento | Flat roof thermal insulation 120m² |
| `infissi_sostituzione` | infissi | PVC double-glazed window replacement |
| `impianto_elettrico_appartamento` | elettrico | Complete electrical wiring 80m² |
| `pittura_interna` | finiture | Interior painting 70m² |

Random scenario generation calls Gemini to produce a realistic 1–3 sentence request in the client's language on demand.

---

## Concurrency model

- `asyncio.Semaphore(MAX_CONCURRENT)` limits active simultaneous simulations.
- Each simulation is an `asyncio.Task`; tasks are tracked by `SimulationManager._active`.
- Stopping a simulation calls `task.cancel()`, which raises `CancelledError` inside the coroutine. The coroutine catches it, updates status to `stopped`, broadcasts the event, then exits cleanly.
- Exceptions that escape `sim.run()` are caught by `_run_with_semaphore` and suppressed (the error was already persisted to DB and broadcast over WS).
- The shared `httpx.AsyncClient` is instantiated once in `agent_client.py` and reused across all simulations for connection pooling efficiency.

---

## Retry and timeout behaviour

The `PreventivatoreClient` uses split `httpx.Timeout`:

| Timeout | Value | Purpose |
|---|---|---|
| `connect` | 10s | TCP handshake + TLS |
| `read` | 300s (configurable) | Server processing time |
| `write` | 10s | Sending request body |
| `pool` | 10s | Acquiring connection from pool |

On `ReadTimeout` or `ConnectTimeout`, the client retries up to `AGENT_MAX_RETRIES` times with an exponential-ish back-off (5s, 10s). SSL certificate verification is disabled (`verify=False`) to handle the self-signed cert on the test server.

---

## Testing

```bash
cd backend
uv run pytest -v
```

Test files:

| File | What it tests |
|---|---|
| `tests/test_questionnaire_parser.py` | Questionnaire response extraction logic |
| `tests/test_simulator.py` | `ClientSimulator` with mocked agent and Gemini clients |

---

## Project structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app, CORS, lifespan hooks
│   ├── config.py            # pydantic-settings: all env vars
│   ├── db.py                # aiosqlite helpers: init, insert, update, query
│   ├── models.py            # Pydantic models: request/response, DB summaries
│   ├── agent_client.py      # PreventivatoreClient — httpx calls to real agent
│   ├── gemini_client.py     # GeminiClient — structured output for questionnaires and replies
│   ├── personas.py          # 5 persona system prompts + get_system_prompt()
│   ├── scenarios.py         # 10 catalog scenarios + random generation via Gemini
│   ├── simulator.py         # ClientSimulator — orchestrates one conversation thread
│   ├── manager.py           # SimulationManager — semaphore, task registry, WS broadcast
│   └── routers/
│       ├── simulations.py   # REST CRUD for simulations
│       ├── catalog.py       # GET /api/personas, GET /api/scenarios
│       └── ws.py            # WebSocket endpoints (global + per-simulation)
├── tests/
│   ├── test_questionnaire_parser.py
│   └── test_simulator.py
├── pyproject.toml
├── .env.example
└── README.md
```
