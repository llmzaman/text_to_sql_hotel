"""
Local chat-history log. Deliberately separate from DATABASE_URL, which
points at the real production HCMS Postgres — that's the client's live
data (read-only for metrics), not a place to write our own app logs.
Chat history is always a local SQLite file inside the container.

Lives under CHAT_HISTORY_DIR if set (a mounted Railway Volume — the
container filesystem is otherwise ephemeral and resets on every
redeploy/restart), falling back to backend/data for local dev. Deliberately
NOT backend/data by default in prod: that path already holds the baked-in
demo PDFs/RAG index/seed DB, and a volume mount there would replace them
with an empty directory on first mount.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DATA_DIR = os.environ.get("CHAT_HISTORY_DIR") or os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "chat_history.db")


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                user_role TEXT NOT NULL,
                client_id INTEGER,
                client_name TEXT,
                supervisor_id INTEGER,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                chart_json TEXT,
                tools_used_json TEXT
            )
        """)


def save_turn(user_role, client_id, client_name, supervisor_id, question, answer, chart, tools_used):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO chat_history (created_at, user_role, client_id, client_name, supervisor_id, "
            "question, answer, chart_json, tools_used_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                user_role, client_id, client_name, supervisor_id,
                question, answer,
                json.dumps(chart) if chart else None,
                json.dumps(tools_used or []),
            ),
        )


def list_history(limit=50, offset=0):
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM chat_history ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "created_at": r["created_at"],
                "user_role": r["user_role"],
                "client_id": r["client_id"],
                "client_name": r["client_name"],
                "supervisor_id": r["supervisor_id"],
                "question": r["question"],
                "answer": r["answer"],
                "chart": json.loads(r["chart_json"]) if r["chart_json"] else None,
                "tools_used": json.loads(r["tools_used_json"]) if r["tools_used_json"] else [],
            }
            for r in rows
        ]


_init()
