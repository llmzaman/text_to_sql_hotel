import os

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.database import SessionLocal
from app.metrics import run_metric, supervisor_client_ids, METRIC_GLOSSARY
from app.schemas import ChatRequest, ChatResponse, DashboardRequest, ClientOut, SupervisorOut
from app.agents.runner import answer_question

app = FastAPI(title="Client Workforce Agentic RAG API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/clients", response_model=list[ClientOut])
def list_clients():
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT c.id, c."clientName", c."clientCity", COUNT(r.id) AS room_count
            FROM client c LEFT JOIN rooms r ON r."clientId" = c.id
            WHERE c."deletedAt" IS NULL
            GROUP BY c.id, c."clientName", c."clientCity"
            ORDER BY c.id
        """)).all()
        return [
            ClientOut(client_id=cid, name=name, city=city, room_count=room_count)
            for cid, name, city, room_count in rows
        ]
    finally:
        db.close()


@app.get("/api/supervisors", response_model=list[SupervisorOut])
def list_supervisors():
    """Supervisors who have at least one client assignment in supervisor_client."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT DISTINCT u.id, u."firstName" || ' ' || u."lastName" AS name
            FROM supervisor_client sc JOIN users u ON u.id = sc."supervisorId"
            ORDER BY name
        """)).all()
        return [SupervisorOut(supervisor_id=sid, name=name) for sid, name in rows]
    finally:
        db.close()


@app.get("/api/supervisors/{supervisor_id}/clients", response_model=list[ClientOut])
def supervisor_clients(supervisor_id: int):
    """Clients a given supervisor is assigned to, per supervisor_client."""
    db = SessionLocal()
    try:
        client_ids = supervisor_client_ids(db, supervisor_id)
        if not client_ids:
            return []
        rows = db.execute(text("""
            SELECT c.id, c."clientName", c."clientCity", COUNT(r.id) AS room_count
            FROM client c LEFT JOIN rooms r ON r."clientId" = c.id
            WHERE c.id = ANY(:ids) AND c."deletedAt" IS NULL
            GROUP BY c.id, c."clientName", c."clientCity"
            ORDER BY c.id
        """), {"ids": client_ids}).all()
        return [
            ClientOut(client_id=cid, name=name, city=city, room_count=room_count)
            for cid, name, city, room_count in rows
        ]
    finally:
        db.close()


@app.get("/api/metrics/glossary")
def metrics_glossary():
    return METRIC_GLOSSARY


@app.post("/api/dashboard")
def dashboard(req: DashboardRequest):
    """Fast, non-agentic path for the dashboard summary cards — calls the
    same semantic-layer metric functions the chat agent uses, but directly,
    so the dashboard loads instantly without an LLM round trip."""
    if req.user_role == "supervisor" and req.client_id is None:
        raise HTTPException(400, "supervisor requests require client_id")
    if req.user_role == "team_supervisor" and req.supervisor_id is None:
        raise HTTPException(400, "team_supervisor requests require supervisor_id")
    kw = dict(role=req.user_role, client_id=req.client_id, supervisor_id=req.supervisor_id, days=req.days)
    try:
        summary = run_metric("total_hours_by_client", **kw)
        headcount = run_metric("headcount_active", **kw)
        absentee = run_metric("absentee_rate", **kw)
        inspections = run_metric("inspection_pass_rate", **kw)
        top_workers = run_metric("top_workers_by_hours", **kw, limit=5)
        trend_client_id = req.client_id or summary["data"][0]["client_id"]
        trend = run_metric("hours_trend_daily", role=req.user_role, client_id=trend_client_id,
                            supervisor_id=req.supervisor_id, days=req.days)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "total_hours_by_client": summary["data"],
        "headcount": headcount["data"],
        "absentee": absentee,
        "inspections": inspections,
        "top_workers": top_workers["data"],
        "hours_trend": trend["data"],
        "trend_client_id": trend_client_id,
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if req.user_role == "supervisor" and req.client_id is None:
        raise HTTPException(400, "supervisor requests require client_id")
    if not os.environ.get("GROQ_API_KEY"):
        raise HTTPException(
            500,
            "GROQ_API_KEY is not set on the server. Add it to backend/.env and restart the API.",
        )
    try:
        result = await answer_question(
            question=req.question,
            role=req.user_role,
            client_id=req.client_id,
            client_name=req.client_name,
            history=[t.model_dump() for t in req.history],
        )
    except Exception as e:
        raise HTTPException(500, f"Agent error: {_root_cause(e)}")
    return result


def _root_cause(e: BaseException) -> str:
    """Unwraps anyio/asyncio ExceptionGroups (raised when the MCP stdio
    session or the LLM call fails inside a TaskGroup) down to the actual
    underlying error, so the API returns something actionable instead of
    a generic 'unhandled errors in a TaskGroup' message."""
    seen = e
    for _ in range(6):
        subs = getattr(seen, "exceptions", None)
        if not subs:
            break
        seen = subs[0]
    return f"{type(seen).__name__}: {seen}"


# Serve the frontend as static files at "/", so `uvicorn app.main:app` alone
# runs the whole application (API + UI) on one port.
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
