# CleanSweep Ops — agentic RAG workforce chatbot

An agentic RAG system for a hotel cleaning workforce platform. Ask questions
in plain English — "top workers this week", "are we compliant with the max
hours policy?" — and get answers pulled from live operational data,
company policy documents, or both, with charts rendered on request.

Built for two roles: **hotel supervisor** (scoped to one hotel) and
**head of supervisors** (sees all hotels).

## Why this isn't "just RAG"

Most of the useful questions here ("total hours worked", "top workers",
"absentee rate") are aggregations over structured data — that's SQL, not
vector search. Embedding shift rows and doing similarity search on them
can't sum or group reliably. So the system splits work by *kind of
question*, not by forcing everything through one retrieval pipeline:

- **Numbers** (hours, headcount, pass rates, rankings, trends) → a small
  whitelisted **semantic layer** of pre-defined metric queries
  (`backend/app/metrics.py`), exposed to the agent as an **MCP server**
  (`backend/app/mcp_server/db_mcp_server.py`). The LLM never writes raw SQL.
- **Policy / procedure questions** (leave rules, max-hours compliance,
  SOP thresholds, contract SLAs) → real **RAG**: four synthetic PDFs,
  chunked and retrieved by TF-IDF + cosine similarity
  (`backend/app/rag/vectorstore.py`).
- An **agent** (LangGraph's `create_react_agent`, running Groq's Llama
  3.3 70B) decides per question which tool(s) to use, optionally calls
  `emit_chart` to request a visualization, then synthesizes an answer.

```
question -> orchestrator (LLM) -> [MCP metrics tool | RAG search tool | both]
                                -> access/role filter (server-side, not just prompted)
                                -> synthesis -> answer (+ optional chart)
```

## What's inside

```
backend/
  app/
    models.py            SQLAlchemy schema (agencies -> hotels -> users -> shifts/tasks/inspections)
    database.py           SQLite engine/session
    seed_data.py          Synthetic data generator (Faker) — 3 hotels, 79 staff, 60 days of ops
    generate_pdfs.py      Synthetic policy PDFs (reportlab)
    metrics.py             The semantic layer: whitelisted, role-scoped metric queries
    rag/vectorstore.py     TF-IDF RAG index over the synthetic PDFs
    mcp_server/
      db_mcp_server.py     MCP server exposing metrics.py as tools over stdio
    agents/
      mcp_client.py        Loads the MCP server's tools into LangChain via langchain-mcp-adapters
      tools.py              Local tools: RAG search, emit_chart
      graph.py               Builds the LangGraph ReAct agent (Groq + tools)
      runner.py               Orchestrates one chat turn end to end
    main.py                FastAPI app: /api/hotels, /api/dashboard, /api/chat; serves the frontend
    schemas.py              Pydantic request/response models
  data/                    SQLite DB, generated PDFs, RAG index (all generated, see Setup)
  requirements.txt
  .env.example
frontend/
  index.html               Single-page chat + dashboard UI (vanilla JS, Chart.js)
```

## Setup

Requires Python 3.11+.

```bash
cd backend
pip install -r requirements.txt

# Generate the synthetic database, PDFs, and RAG index (takes ~10s)
python -m app.seed_data
python -m app.generate_pdfs
python -m app.rag.vectorstore     # builds the TF-IDF index

# Add your Groq key
cp .env.example .env
# edit .env and paste your key from https://console.groq.com/keys
```

Run the app (serves both the API and the frontend on one port):

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** — the chat UI, dashboard cards, and role/hotel
switcher are all there. API docs are at http://localhost:8000/docs.

## Trying it out

Switch the role selector between "Hotel supervisor" (pick a hotel) and
"Head of supervisors" (sees all hotels, or one at a time). Try:

- "How many total hours were worked in cleaning vs checking this week?"
- "Who are the top 5 workers by hours this week?"
- "What's our absentee rate and who's been absent the most?"
- "Compare all hotels on hours, headcount, absentee rate, and inspection pass rate" (head of supervisors — triggers a chart)
- "What happens if a worker exceeds 10 hours of actual work in a single day, per policy?" (pure RAG)
- "Are we compliant with the max-hours policy this week?" (hybrid: numbers + policy)

## Design notes / things worth knowing before extending this

- **Embeddings are TF-IDF, not neural.** This runs fully offline with no
  external embedding API or model download — deliberate for a portable
  demo. `rag/vectorstore.py` is the only file you'd touch to swap in
  Chroma/FAISS + a real embedding model (OpenAI, Cohere, or a local
  sentence-transformers model); nothing in the agent layer needs to change,
  since it only calls `.search(query, k)`.
- **Row-level security is enforced twice.** The agent's system prompt tells
  it to pass the right `role`/`hotel_id`, but the actual enforcement is in
  `metrics.py:_resolve_hotel_scope` — a supervisor's `hotel_id` is pinned
  server-side regardless of what's requested. Don't rely on prompting alone
  for access control in a real deployment.
- **The semantic layer is the point.** `METRIC_GLOSSARY` in `metrics.py` is
  intentionally small and named in business language ("top_workers_by_hours",
  not "shifts_join_users_group_by"). Every new metric you add here is a new
  well-defined, consistent building block the agent can reach for — resist
  the temptation to let the LLM freehand SQL against the live tables.
- **MCP is used for the data tools, not for RAG.** The metrics/SQL layer is
  exposed as an MCP server because it's the kind of tool you'd genuinely
  want shared across multiple agents/clients (this chatbot, but also
  Claude Desktop, another internal tool, etc.). The RAG search and chart
  tools stay as plain LangChain tools since they're specific to this app.
- **`mcp` is pinned to `1.29.0`** in requirements.txt. The `mcp` package's
  2.0 release renamed `FastMCP` to `MCPServer` and broke compatibility with
  `langchain-mcp-adapters` at the time this was built — if you upgrade,
  check that compatibility first.
- **Dashboard cards call `metrics.py` directly**, bypassing the LLM
  entirely, so the sidebar loads instantly. Only the chat endpoint goes
  through the agent. This is a common pattern: reserve the LLM for
  open-ended questions, keep fixed dashboards on the fast path.

## Deploy (Docker / Railway)

Single container: FastAPI serves the API and the static frontend on one
port (`app/main.py` mounts `frontend/` at `/`). The MCP metrics server
runs as a stdio subprocess inside the same container — no second service.

```bash
docker build -t hotel-rag .
docker run -p 8000:8000 -e GROQ_API_KEY=your_key hotel-rag
```

Railway: connect the repo (root `Dockerfile` + `railway.toml` are picked
up automatically), then set `GROQ_API_KEY` in the service's variables.
Railway injects `PORT` — the container's `CMD` binds to it. `/api/health`
is wired as the healthcheck path.

Add a Railway Postgres plugin and it auto-injects `DATABASE_URL` into the
service — `database.py` picks it up and switches off SQLite automatically
(falls back to the local SQLite file only when `DATABASE_URL` is unset).
Seed the fresh database once after the plugin is attached:

```bash
railway run python -m app.seed_data
```

API docs (Swagger UI) are served at `/docs`, ReDoc at `/redoc`, raw
OpenAPI schema at `/openapi.json` — enabled by default, no extra setup.

## Extending this

- Add a new metric: write a `_m_your_metric` function in `metrics.py`,
  register it in `METRIC_GLOSSARY` and `_METRIC_FUNCS`. No agent code
  changes needed — `get_schema_glossary` picks it up automatically.
- Add a new policy document: drop a PDF into `backend/data/pdfs/` and
  re-run `python -m app.rag.vectorstore`.
- Swap SQLite for Postgres: only `database.py` needs to change
  (`DATABASE_URL`); everything else uses the SQLAlchemy ORM layer.
