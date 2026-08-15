import os

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import SessionLocal
from app.models import Client
from app.metrics import run_metric, METRIC_GLOSSARY
from app.schemas import ChatRequest, ChatResponse, DashboardRequest, ClientOut
from app.agents.runner import answer_question

app = FastAPI(title="Hotel Workforce Agentic RAG API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/hotels", response_model=list[HotelOut])
def list_hotels():
    db = SessionLocal()
    try:
        hotels = db.query(Hotel).all()
        return [
            HotelOut(hotel_id=h.hotel_id, name=h.name, city=h.city, room_count=h.room_count)
            for h in hotels
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
    if req.user_role == "supervisor" and req.hotel_id is None:
        raise HTTPException(400, "supervisor requests require hotel_id")
    try:
        summary = run_metric("total_hours_by_hotel", role=req.user_role, hotel_id=req.hotel_id, days=req.days)
        headcount = run_metric("headcount_active", role=req.user_role, hotel_id=req.hotel_id, days=req.days)
        absentee = run_metric("absentee_rate", role=req.user_role, hotel_id=req.hotel_id, days=req.days)
        inspections = run_metric("inspection_pass_rate", role=req.user_role, hotel_id=req.hotel_id, days=req.days)
        top_workers = run_metric("top_workers_by_hours", role=req.user_role, hotel_id=req.hotel_id, days=req.days, limit=5)
        trend_hotel_id = req.hotel_id or summary["data"][0]["hotel_id"]
        trend = run_metric("hours_trend_daily", role=req.user_role, hotel_id=trend_hotel_id, days=req.days)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "total_hours_by_hotel": summary["data"],
        "headcount": headcount["data"],
        "absentee": absentee,
        "inspections": inspections,
        "top_workers": top_workers["data"],
        "hours_trend": trend["data"],
        "trend_hotel_id": trend_hotel_id,
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if req.user_role == "supervisor" and req.hotel_id is None:
        raise HTTPException(400, "supervisor requests require hotel_id")
    if not os.environ.get("GROQ_API_KEY"):
        raise HTTPException(
            500,
            "GROQ_API_KEY is not set on the server. Add it to backend/.env and restart the API.",
        )
    try:
        result = await answer_question(
            question=req.question,
            role=req.user_role,
            hotel_id=req.hotel_id,
            hotel_name=req.hotel_name,
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
