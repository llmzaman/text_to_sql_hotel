"""
The "semantic layer" from the design doc: a small, whitelisted set of
business metrics with fixed, parameterized SQL behind them. The LLM never
writes free-form SQL against production tables — it picks a metric name
from this glossary and supplies parameters. This is what keeps answers
consistent (one definition of "top workers", reused everywhere) and safe
(no injection surface, no accidental full-table scans or writes).

Row-level security: every function takes `role` + `client_id` and a
supervisor's `client_id` is always enforced server-side, never trusted from
the caller/LLM alone.

Queries here run against the real HCMS production schema (client, users,
worker_shifts, attendance_history, room_history, rooms, worker_types) via
read-only raw SQL — the schema doesn't map onto a simple ORM model, and
column names are quoted camelCase throughout.

Data-quality note: a small number of attendance_history rows have a
checkOut days after checkIn (forgotten checkout). Per-shift hours are
capped at 16h so those outliers don't blow up aggregates.
"""
from datetime import date, timedelta

from sqlalchemy import text

from app.database import SessionLocal

METRIC_GLOSSARY = {
    "total_hours_by_client": {
        "description": "Total actual hours worked (from check-in/check-out), split by cleaning-staff vs checking-staff, per client, over the trailing N days.",
        "params": ["client_id (optional for head_supervisor)", "days"],
    },
    "hours_trend_daily": {
        "description": "Daily total actual hours worked for a client over the trailing N days — use for line-chart trend questions.",
        "params": ["client_id (required)", "days"],
    },
    "top_workers_by_hours": {
        "description": "Ranks workers by total actual hours worked over the trailing N days.",
        "params": ["client_id (optional for head_supervisor)", "days", "limit"],
    },
    "top_workers_by_tasks": {
        "description": "Ranks cleaners by number of rooms marked clean over the trailing N days.",
        "params": ["client_id (optional for head_supervisor)", "days", "limit"],
    },
    "headcount_active": {
        "description": "Count of distinct workers with a scheduled shift in the trailing N days, per client.",
        "params": ["client_id (optional for head_supervisor)", "days"],
    },
    "absentee_rate": {
        "description": "Absence rate = scheduled shifts with no matching check-in / total scheduled shifts, per client, over the trailing N days. Also returns top absent workers.",
        "params": ["client_id (optional for head_supervisor)", "days"],
    },
    "inspection_pass_rate": {
        "description": "Room-inspection pass rate per client over the trailing N days (rooms marked clean / rooms checked), plus per-checker breakdown.",
        "params": ["client_id (optional for head_supervisor)", "days"],
    },
    "overtime_hours_by_worker": {
        "description": "Workers with the most hours worked beyond their assigned/scheduled hours over the trailing N days.",
        "params": ["client_id (optional for head_supervisor)", "days", "limit"],
    },
    "worker_fail_rate": {
        "description": "Cleaners ranked by inspection fail rate (rooms left unclean after check) over the trailing N days — flags workers needing coaching.",
        "params": ["client_id (optional for head_supervisor)", "days", "limit"],
    },
    "client_comparison_summary": {
        "description": "Side-by-side summary across all clients: total hours, headcount, absentee rate, inspection pass rate. head_supervisor only.",
        "params": ["days"],
    },
}

# Per-shift hours worked, floored at 0 and capped at 16 to absorb bad data
# (forgotten checkouts spanning multiple days).
_HOURS_EXPR = (
    'GREATEST(LEAST('
    'EXTRACT(EPOCH FROM (ah."checkOut" - ah."checkIn"))/3600.0 - COALESCE(ah."breakTime", 0)/60.0'
    ', 16), 0)'
)


def _resolve_client_scope(db, role: str, client_id):
    """Enforces row-level access: supervisors are pinned to their client."""
    if role == "supervisor":
        if client_id is None:
            raise ValueError("supervisor role requires a client_id")
        return [client_id]
    # head_supervisor: all clients, or a single one if specified
    if client_id is not None:
        return [client_id]
    rows = db.execute(text('SELECT id FROM client WHERE "deletedAt" IS NULL ORDER BY id')).all()
    return [r[0] for r in rows]


def run_metric(metric: str, role: str, client_id=None, days: int = 7, limit: int = 10):
    if metric not in METRIC_GLOSSARY:
        raise ValueError(f"Unknown metric '{metric}'. Valid metrics: {list(METRIC_GLOSSARY)}")

    db = SessionLocal()
    try:
        client_ids = _resolve_client_scope(db, role, client_id)
        since = date.today() - timedelta(days=days)
        fn = _METRIC_FUNCS[metric]
        return fn(db, client_ids, since, limit)
    finally:
        db.close()


def _client_name_map(db, client_ids):
    if not client_ids:
        return {}
    rows = db.execute(
        text('SELECT id, "clientName" FROM client WHERE id = ANY(:ids)'), {"ids": client_ids}
    ).all()
    return {r[0]: r[1] for r in rows}


def _m_total_hours_by_client(db, client_ids, since, limit):
    names = _client_name_map(db, client_ids)
    out = []
    for cid in client_ids:
        cleaning = db.execute(text(f"""
            SELECT COALESCE(SUM({_HOURS_EXPR}), 0)
            FROM worker_shifts ws
            JOIN attendance_history ah ON ah."userId" = ws."workerId" AND ah.date = ws.date
            LEFT JOIN worker_types wt ON wt.id = ws."workerTypeId"
            WHERE ws."clientId" = :cid AND ws.date >= :since
              AND ah."checkIn" IS NOT NULL AND ah."checkOut" IS NOT NULL
              AND wt.name IS DISTINCT FROM 'checker'
        """), {"cid": cid, "since": since}).scalar()
        checking = db.execute(text(f"""
            SELECT COALESCE(SUM({_HOURS_EXPR}), 0)
            FROM worker_shifts ws
            JOIN attendance_history ah ON ah."userId" = ws."workerId" AND ah.date = ws.date
            JOIN worker_types wt ON wt.id = ws."workerTypeId"
            WHERE ws."clientId" = :cid AND ws.date >= :since
              AND ah."checkIn" IS NOT NULL AND ah."checkOut" IS NOT NULL
              AND wt.name = 'checker'
        """), {"cid": cid, "since": since}).scalar()
        cleaning, checking = float(cleaning), float(checking)
        out.append({
            "client": names.get(cid), "client_id": cid,
            "cleaning_hours": round(cleaning, 1), "checking_hours": round(checking, 1),
            "total_hours": round(cleaning + checking, 1),
        })
    return {"metric": "total_hours_by_client", "window_days": None, "data": out}


def _m_hours_trend_daily(db, client_ids, since, limit):
    cid = client_ids[0]
    rows = db.execute(text(f"""
        SELECT ws.date, COALESCE(SUM({_HOURS_EXPR}), 0)
        FROM worker_shifts ws
        JOIN attendance_history ah ON ah."userId" = ws."workerId" AND ah.date = ws.date
        WHERE ws."clientId" = :cid AND ws.date >= :since
          AND ah."checkIn" IS NOT NULL AND ah."checkOut" IS NOT NULL
        GROUP BY ws.date ORDER BY ws.date
    """), {"cid": cid, "since": since}).all()
    data = [{"date": str(d), "hours": round(float(h), 1)} for d, h in rows]
    return {"metric": "hours_trend_daily", "client_id": cid, "data": data}


def _m_top_workers_by_hours(db, client_ids, since, limit):
    rows = db.execute(text(f"""
        SELECT u.id, u."firstName" || ' ' || u."lastName" AS worker,
               COALESCE(wt."displayName", 'Worker') AS worker_type,
               c."clientName" AS client, COALESCE(SUM({_HOURS_EXPR}), 0) AS hrs
        FROM worker_shifts ws
        JOIN attendance_history ah ON ah."userId" = ws."workerId" AND ah.date = ws.date
        JOIN users u ON u.id = ws."workerId"
        JOIN client c ON c.id = ws."clientId"
        LEFT JOIN worker_types wt ON wt.id = ws."workerTypeId"
        WHERE ws."clientId" = ANY(:cids) AND ws.date >= :since
          AND ah."checkIn" IS NOT NULL AND ah."checkOut" IS NOT NULL
        GROUP BY u.id, worker, worker_type, client
        ORDER BY hrs DESC LIMIT :limit
    """), {"cids": client_ids, "since": since, "limit": limit}).all()
    data = [{"worker": w, "role": wt, "client": c, "hours": round(float(h), 1)} for _, w, wt, c, h in rows]
    return {"metric": "top_workers_by_hours", "data": data}


def _m_top_workers_by_tasks(db, client_ids, since, limit):
    rows = db.execute(text("""
        SELECT u.id, u."firstName" || ' ' || u."lastName" AS worker,
               c."clientName" AS client, COUNT(rh.id) AS n
        FROM room_history rh
        JOIN worker_shifts ws ON ws.id = rh."workerShiftId"
        JOIN users u ON u.id = ws."workerId"
        JOIN client c ON c.id = ws."clientId"
        WHERE ws."clientId" = ANY(:cids) AND rh.date >= :since AND rh.status = 'clean'
        GROUP BY u.id, worker, client
        ORDER BY n DESC LIMIT :limit
    """), {"cids": client_ids, "since": since, "limit": limit}).all()
    data = [{"worker": w, "client": c, "rooms_cleaned": n} for _, w, c, n in rows]
    return {"metric": "top_workers_by_tasks", "data": data}


def _m_headcount_active(db, client_ids, since, limit):
    names = _client_name_map(db, client_ids)
    out = []
    for cid in client_ids:
        n = db.execute(text("""
            SELECT COUNT(DISTINCT "workerId") FROM worker_shifts
            WHERE "clientId" = :cid AND date >= :since
        """), {"cid": cid, "since": since}).scalar()
        out.append({"client": names.get(cid), "client_id": cid, "active_headcount": n})
    return {"metric": "headcount_active", "data": out}


def _m_absentee_rate(db, client_ids, since, limit):
    names = _client_name_map(db, client_ids)
    out = []
    for cid in client_ids:
        total = db.execute(text("""
            SELECT COUNT(*) FROM worker_shifts WHERE "clientId" = :cid AND date >= :since
        """), {"cid": cid, "since": since}).scalar()
        absent = db.execute(text("""
            SELECT COUNT(*) FROM worker_shifts ws
            WHERE ws."clientId" = :cid AND ws.date >= :since
              AND NOT EXISTS (
                SELECT 1 FROM attendance_history ah
                WHERE ah."userId" = ws."workerId" AND ah.date = ws.date AND ah."checkIn" IS NOT NULL
              )
        """), {"cid": cid, "since": since}).scalar()
        rate = round(100 * absent / total, 1) if total else 0.0
        out.append({"client": names.get(cid), "client_id": cid, "absentee_rate_pct": rate,
                     "absent_shift_days": absent, "total_shift_days": total})

    top_absent = db.execute(text("""
        SELECT u.id, u."firstName" || ' ' || u."lastName" AS worker, COUNT(*) AS n
        FROM worker_shifts ws
        JOIN users u ON u.id = ws."workerId"
        WHERE ws."clientId" = ANY(:cids) AND ws.date >= :since
          AND NOT EXISTS (
            SELECT 1 FROM attendance_history ah
            WHERE ah."userId" = ws."workerId" AND ah.date = ws.date AND ah."checkIn" IS NOT NULL
          )
        GROUP BY u.id, worker ORDER BY n DESC LIMIT 5
    """), {"cids": client_ids, "since": since}).all()
    return {"metric": "absentee_rate", "by_client": out,
            "top_absent_workers": [{"worker": w, "absences": n} for _, w, n in top_absent]}


def _m_inspection_pass_rate(db, client_ids, since, limit):
    names = _client_name_map(db, client_ids)
    out = []
    for cid in client_ids:
        total = db.execute(text("""
            SELECT COUNT(*) FROM room_history rh JOIN rooms r ON r.id = rh."roomId"
            WHERE r."clientId" = :cid AND rh."isChecked" = true AND rh.date >= :since
        """), {"cid": cid, "since": since}).scalar()
        passed = db.execute(text("""
            SELECT COUNT(*) FROM room_history rh JOIN rooms r ON r.id = rh."roomId"
            WHERE r."clientId" = :cid AND rh."isChecked" = true AND rh.date >= :since AND rh.status = 'clean'
        """), {"cid": cid, "since": since}).scalar()
        rate = round(100 * passed / total, 1) if total else None
        out.append({"client": names.get(cid), "client_id": cid, "pass_rate_pct": rate, "inspections": total})

    by_checker = db.execute(text("""
        SELECT u.id, u."firstName" || ' ' || u."lastName" AS checker,
               COUNT(*) AS n, SUM(CASE WHEN rh.status = 'clean' THEN 1 ELSE 0 END) AS passed
        FROM room_history rh
        JOIN rooms r ON r.id = rh."roomId"
        JOIN worker_shifts ws ON ws.id = rh."checkerShiftId"
        JOIN users u ON u.id = ws."workerId"
        WHERE r."clientId" = ANY(:cids) AND rh."isChecked" = true AND rh.date >= :since
        GROUP BY u.id, checker ORDER BY n DESC LIMIT :limit
    """), {"cids": client_ids, "since": since, "limit": limit}).all()
    return {"metric": "inspection_pass_rate", "by_client": out,
            "by_checker": [{"checker": c, "inspections": n,
                             "pass_rate_pct": round(100 * p / n, 1) if n else None} for _, c, n, p in by_checker]}


def _m_overtime_hours_by_worker(db, client_ids, since, limit):
    rows = db.execute(text(f"""
        SELECT u.id, u."firstName" || ' ' || u."lastName" AS worker, c."clientName" AS client,
               COALESCE(SUM(GREATEST({_HOURS_EXPR} - COALESCE(ws."assignHours", 0), 0)), 0) AS ot
        FROM worker_shifts ws
        JOIN attendance_history ah ON ah."userId" = ws."workerId" AND ah.date = ws.date
        JOIN users u ON u.id = ws."workerId"
        JOIN client c ON c.id = ws."clientId"
        WHERE ws."clientId" = ANY(:cids) AND ws.date >= :since
          AND ah."checkIn" IS NOT NULL AND ah."checkOut" IS NOT NULL
        GROUP BY u.id, worker, client
        ORDER BY ot DESC LIMIT :limit
    """), {"cids": client_ids, "since": since, "limit": limit}).all()
    data = [{"worker": w, "client": c, "overtime_hours": round(float(ot), 1)} for _, w, c, ot in rows]
    return {"metric": "overtime_hours_by_worker", "data": data}


def _m_worker_fail_rate(db, client_ids, since, limit):
    rows = db.execute(text("""
        SELECT u.id, u."firstName" || ' ' || u."lastName" AS worker, c."clientName" AS client,
               COUNT(*) AS total, SUM(CASE WHEN rh.status = 'unclean' THEN 1 ELSE 0 END) AS fails
        FROM room_history rh
        JOIN rooms r ON r.id = rh."roomId"
        JOIN worker_shifts ws ON ws.id = rh."workerShiftId"
        JOIN users u ON u.id = ws."workerId"
        JOIN client c ON c.id = ws."clientId"
        WHERE ws."clientId" = ANY(:cids) AND rh."isChecked" = true AND rh.date >= :since
          AND rh.status IN ('clean', 'unclean')
        GROUP BY u.id, worker, client
        HAVING COUNT(*) >= 3
        ORDER BY (SUM(CASE WHEN rh.status = 'unclean' THEN 1 ELSE 0 END)::float / COUNT(*)) DESC
        LIMIT :limit
    """), {"cids": client_ids, "since": since, "limit": limit}).all()
    data = [{"worker": w, "client": c, "inspections": t, "fails": f,
             "fail_rate_pct": round(100 * f / t, 1) if t else 0} for _, w, c, t, f in rows]
    return {"metric": "worker_fail_rate", "data": data}


def _m_client_comparison_summary(db, client_ids, since, limit):
    hours = _m_total_hours_by_client(db, client_ids, since, limit)["data"]
    head = _m_headcount_active(db, client_ids, since, limit)["data"]
    absent = _m_absentee_rate(db, client_ids, since, limit)["by_client"]
    pass_rate = _m_inspection_pass_rate(db, client_ids, since, limit)["by_client"]

    merged = {}
    for row in hours:
        merged[row["client_id"]] = {"client": row["client"], "total_hours": row["total_hours"]}
    for row in head:
        merged[row["client_id"]]["active_headcount"] = row["active_headcount"]
    for row in absent:
        merged[row["client_id"]]["absentee_rate_pct"] = row["absentee_rate_pct"]
    for row in pass_rate:
        merged[row["client_id"]]["inspection_pass_rate_pct"] = row["pass_rate_pct"]

    return {"metric": "client_comparison_summary", "data": list(merged.values())}


_METRIC_FUNCS = {
    "total_hours_by_client": _m_total_hours_by_client,
    "hours_trend_daily": _m_hours_trend_daily,
    "top_workers_by_hours": _m_top_workers_by_hours,
    "top_workers_by_tasks": _m_top_workers_by_tasks,
    "headcount_active": _m_headcount_active,
    "absentee_rate": _m_absentee_rate,
    "inspection_pass_rate": _m_inspection_pass_rate,
    "overtime_hours_by_worker": _m_overtime_hours_by_worker,
    "worker_fail_rate": _m_worker_fail_rate,
    "client_comparison_summary": _m_client_comparison_summary,
}
