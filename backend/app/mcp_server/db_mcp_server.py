"""
MCP server exposing the workforce database as a set of tools over stdio.

This is the standard MCP pattern: the database logic lives behind a tool
boundary that any MCP-compatible client (this app's LangGraph agent, but
also Claude Desktop, another agent, etc.) can call without knowing SQL or
the schema internals. Two tools are exposed:

  - run_metric_query(metric, client_id, role, ...): executes one of a
    whitelisted set of pre-defined, parameterized queries (the "semantic
    layer" from the design doc). This is what keeps the LLM from having to
    freehand SQL against a live production database.
  - get_schema_glossary(): returns the metric glossary/table doc so the
    calling agent knows what's available and how each metric is defined.

Run standalone for testing:  python -m app.mcp_server.db_mcp_server
The FastAPI backend launches this as a subprocess via stdio (see
app/agents/mcp_client.py).
"""
import json
import logging
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mcp.server.fastmcp import FastMCP

from app.metrics import METRIC_GLOSSARY, run_metric

mcp = FastMCP("client-workforce-db")
logger = logging.getLogger("db_mcp_server")



@mcp.tool()
def get_schema_glossary() -> str:
    """Return the list of available business metrics, what each one means,
    and what parameters it accepts (client_id, role, date range). Call this
    first if you're unsure which metric name to use in run_metric_query."""
    return json.dumps(METRIC_GLOSSARY, indent=2)


@mcp.tool()
def run_metric_query(
    metric: str,
    role: str,
    client_id: int | None = None,
    supervisor_id: int | None = None,
    days: int = 7,
    limit: int = 10,
) -> str:
    """Run a whitelisted, parameterized business metric query against the
    client workforce database and return JSON results.

    Args:
        metric: one of the metric names from get_schema_glossary, e.g.
            "total_hours_by_client", "top_workers_by_hours",
            "absentee_rate", "inspection_pass_rate", "headcount_active",
            "overtime_hours_by_worker", "hours_trend_daily".
        role: "supervisor", "team_supervisor", or "head_supervisor". Enforces
            row-level access:
              - supervisor: always restricted to their own client_id.
              - team_supervisor: restricted to the clients assigned to
                supervisor_id via supervisor_client, regardless of what
                client_id is passed in.
              - head_supervisor: unrestricted.
        client_id: restrict to a single client. Required for supervisor role.
            For team_supervisor, must be one of that supervisor's assigned
            clients if given, otherwise all their clients are used. Head
            supervisors may omit it to see all clients.
        supervisor_id: required for team_supervisor role — identifies which
            supervisor's client assignments to scope to.
        days: size of the trailing date window, e.g. 7 for "last week", 30
            for "last month".
        limit: max rows to return for ranking-style metrics.
    """
    try:
        result = run_metric(metric=metric, role=role, client_id=client_id,
                             supervisor_id=supervisor_id, days=days, limit=limit)
        return json.dumps(result, default=str)
    except Exception as e:
        # Print the full traceback to stderr (captured in Railway's deploy
        # logs) — the LLM only ever sees str(e), so without this the real
        # cause of a failure is invisible from outside.
        print(
            f"run_metric_query failed: metric={metric} role={role} client_id={client_id} "
            f"supervisor_id={supervisor_id} days={days}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    mcp.run(transport="stdio")
