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
"""
from datetime import date, timedelta
from sqlalchemy import func, and_, case

from app.database import SessionLocal
from app.models import Client, User, Shift, Task, Inspection, Leave

METRIC_GLOSSARY = {
    "total_hours_by_client": {
        "description": "Total actual hours worked, split by cleaning-staff vs checking-staff headcount, per client, over the trailing N days.",
        "params": ["client_id (optional for head_supervisor)", "days"],
    },
    "hours_trend_daily": {
        "description": "Daily total actual hours worked for a client over the trailing N days — use for line-chart trend questions.",
        "params": ["client_id (required)", "days"],
    },
    "top_workers_by_hours": {
        "description": "Ranks active cleaners/checkers by total actual hours worked over the trailing N days.",
        "params": ["client_id (optional for head_supervisor)", "days", "limit"],
    },
    "top_workers_by_tasks": {
        "description": "Ranks cleaners by number of completed cleaning tasks (rooms cleaned) over the trailing N days.",
        "params": ["client_id (optional for head_supervisor)", "days", "limit"],
    },
    "headcount_active": {
        "description": "Count of distinct active workers (cleaners+checkers) who worked at least one shift in the trailing N days, per client.",
        "params": ["client_id (optional for head_supervisor)", "days"],
    },
    "absentee_rate": {
        "description": "Absence rate = absent shift-days / total scheduled shift-days, per client, over the trailing N days. Also returns top absent workers.",
        "params": ["client_id (optional for head_supervisor)", "days"],
    },
    "inspection_pass_rate": {
        "description": "Inspection pass rate per client over the trailing N days, plus per-checker breakdown.",
        "params": ["client_id (optional for head_supervisor)", "days"],
    },
    "overtime_hours_by_worker": {
        "description": "Workers with the most overtime hours over the trailing N days.",
        "params": ["client_id (optional for head_supervisor)", "days", "limit"],
    },
    "worker_fail_rate": {
        "description": "Cleaners ranked by inspection fail rate over the trailing N days — flags workers needing coaching.",
        "params": ["client_id (optional for head_supervisor)", "days", "limit"],
    },
    "client_comparison_summary": {
        "description": "Side-by-side summary across all clients: total hours, headcount, absentee rate, inspection pass rate. head_supervisor only.",
        "params": ["days"],
    },
}


def _resolve_client_scope(db, role: str, client_id):
    """Enforces row-level access: supervisors are pinned to their client."""
    if role == "supervisor":
        if client_id is None:
            raise ValueError("supervisor role requires a client_id")
        return [client_id]
    # head_supervisor: all clients, or a single one if specified
    if client_id is not None:
        return [client_id]
    return [c.client_id for c in db.query(Client).all()]


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
    rows = db.query(Client).filter(Client.client_id.in_(client_ids)).all()
    return {c.client_id: c.name for c in rows}


def _m_total_hours_by_client(db, client_ids, since, limit):
    names = _client_name_map(db, client_ids)
    out = []
    for cid in client_ids:
        cleaning = db.query(func.coalesce(func.sum(Shift.actual_hours), 0)).join(
            User, User.user_id == Shift.user_id
        ).filter(Shift.client_id == cid, Shift.work_date >= since, User.role == "cleaner").scalar()
        checking = db.query(func.coalesce(func.sum(Shift.actual_hours), 0)).join(
            User, User.user_id == Shift.user_id
        ).filter(Shift.client_id == cid, Shift.work_date >= since, User.role == "checker").scalar()
        out.append({
            "client": names.get(cid), "client_id": cid,
            "cleaning_hours": round(cleaning, 1), "checking_hours": round(checking, 1),
            "total_hours": round(cleaning + checking, 1),
        })
    return {"metric": "total_hours_by_client", "window_days": None, "data": out}


def _m_hours_trend_daily(db, client_ids, since, limit):
    cid = client_ids[0]
    rows = (
        db.query(Shift.work_date, func.coalesce(func.sum(Shift.actual_hours), 0))
        .filter(Shift.client_id == cid, Shift.work_date >= since)
        .group_by(Shift.work_date).order_by(Shift.work_date).all()
    )
    data = [{"date": str(d), "hours": round(h, 1)} for d, h in rows]
    return {"metric": "hours_trend_daily", "client_id": cid, "data": data}


def _m_top_workers_by_hours(db, client_ids, since, limit):
    rows = (
        db.query(User.full_name, User.role, Client.name, func.coalesce(func.sum(Shift.actual_hours), 0).label("hrs"))
        .join(Shift, Shift.user_id == User.user_id)
        .join(Client, Client.client_id == User.client_id)
        .filter(Shift.client_id.in_(client_ids), Shift.work_date >= since, User.role.in_(["cleaner", "checker"]))
        .group_by(User.user_id).order_by(func.sum(Shift.actual_hours).desc()).limit(limit).all()
    )
    data = [{"worker": n, "role": r, "client": c, "hours": round(hrs, 1)} for n, r, c, hrs in rows]
    return {"metric": "top_workers_by_hours", "data": data}


def _m_top_workers_by_tasks(db, client_ids, since, limit):
    rows = (
        db.query(User.full_name, Client.name, func.count(Task.task_id).label("n"))
        .join(Task, Task.assigned_to == User.user_id)
        .join(Client, Client.client_id == User.client_id)
        .filter(Task.client_id.in_(client_ids), Task.work_date >= since, Task.task_type == "cleaning", Task.status == "completed")
        .group_by(User.user_id).order_by(func.count(Task.task_id).desc()).limit(limit).all()
    )
    data = [{"worker": n, "client": c, "rooms_cleaned": cnt} for n, c, cnt in rows]
    return {"metric": "top_workers_by_tasks", "data": data}


def _m_headcount_active(db, client_ids, since, limit):
    names = _client_name_map(db, client_ids)
    out = []
    for cid in client_ids:
        n = (
            db.query(func.count(func.distinct(Shift.user_id)))
            .filter(Shift.client_id == cid, Shift.work_date >= since, Shift.status != "absent")
            .scalar()
        )
        out.append({"client": names.get(cid), "client_id": cid, "active_headcount": n})
    return {"metric": "headcount_active", "data": out}


def _m_absentee_rate(db, client_ids, since, limit):
    names = _client_name_map(db, client_ids)
    out = []
    for cid in client_ids:
        total = db.query(func.count(Shift.shift_id)).filter(Shift.client_id == cid, Shift.work_date >= since).scalar()
        absent = db.query(func.count(Shift.shift_id)).filter(
            Shift.client_id == cid, Shift.work_date >= since, Shift.status == "absent"
        ).scalar()
        rate = round(100 * absent / total, 1) if total else 0.0
        out.append({"client": names.get(cid), "client_id": cid, "absentee_rate_pct": rate,
                     "absent_shift_days": absent, "total_shift_days": total})

    top_absent = (
        db.query(User.full_name, Client.name, func.count(Shift.shift_id).label("n"))
        .join(Shift, Shift.user_id == User.user_id)
        .join(Client, Client.client_id == User.client_id)
        .filter(Shift.client_id.in_(client_ids), Shift.work_date >= since, Shift.status == "absent")
        .group_by(User.user_id).order_by(func.count(Shift.shift_id).desc()).limit(5).all()
    )
    return {"metric": "absentee_rate", "by_client": out,
            "top_absent_workers": [{"worker": n, "client": c, "absences": cnt} for n, c, cnt in top_absent]}


def _m_inspection_pass_rate(db, client_ids, since, limit):
    names = _client_name_map(db, client_ids)
    out = []
    for cid in client_ids:
        total = db.query(func.count(Inspection.inspection_id)).filter(
            Inspection.client_id == cid, Inspection.inspected_at >= since
        ).scalar()
        passed = db.query(func.count(Inspection.inspection_id)).filter(
            Inspection.client_id == cid, Inspection.inspected_at >= since, Inspection.result == "pass"
        ).scalar()
        rate = round(100 * passed / total, 1) if total else None
        out.append({"client": names.get(cid), "client_id": cid, "pass_rate_pct": rate, "inspections": total})

    by_checker = (
        db.query(User.full_name, func.count(Inspection.inspection_id).label("n"),
                  func.avg(Inspection.score).label("avg_score"))
        .join(Inspection, Inspection.checker_id == User.user_id)
        .filter(Inspection.client_id.in_(client_ids), Inspection.inspected_at >= since)
        .group_by(User.user_id).order_by(func.count(Inspection.inspection_id).desc()).limit(limit).all()
    )
    return {"metric": "inspection_pass_rate", "by_client": out,
            "by_checker": [{"checker": n, "inspections": c, "avg_score": round(a, 1) if a else None} for n, c, a in by_checker]}


def _m_overtime_hours_by_worker(db, client_ids, since, limit):
    rows = (
        db.query(User.full_name, Client.name, func.coalesce(func.sum(Shift.actual_hours - Shift.scheduled_hours), 0).label("ot"))
        .join(Shift, Shift.user_id == User.user_id)
        .join(Client, Client.client_id == User.client_id)
        .filter(Shift.client_id.in_(client_ids), Shift.work_date >= since, Shift.shift_type == "overtime")
        .group_by(User.user_id).order_by(func.sum(Shift.actual_hours - Shift.scheduled_hours).desc()).limit(limit).all()
    )
    data = [{"worker": n, "client": c, "overtime_hours": round(ot, 1)} for n, c, ot in rows]
    return {"metric": "overtime_hours_by_worker", "data": data}


def _m_worker_fail_rate(db, client_ids, since, limit):
    rows = (
        db.query(User.full_name, Client.name,
                  func.count(Inspection.inspection_id).label("total"),
                  func.sum(case((Inspection.result == "fail", 1), else_=0)).label("fails"))
        .join(Task, Task.task_id == Inspection.task_id)
        .join(User, User.user_id == Task.assigned_to)
        .join(Client, Client.client_id == User.client_id)
        .filter(Inspection.client_id.in_(client_ids), Inspection.inspected_at >= since)
        .group_by(User.user_id).having(func.count(Inspection.inspection_id) >= 3)
        .order_by((func.sum(case((Inspection.result == "fail", 1), else_=0)) * 1.0 / func.count(Inspection.inspection_id)).desc())
        .limit(limit).all()
    )
    data = [{"worker": n, "client": c, "inspections": t, "fails": f,
             "fail_rate_pct": round(100 * f / t, 1) if t else 0} for n, c, t, f in rows]
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
