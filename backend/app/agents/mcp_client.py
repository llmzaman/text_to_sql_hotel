"""
Bridges the MCP server (app/mcp_server/db_mcp_server.py) into LangChain
tools the LangGraph agent can call directly. This is the standard
langchain-mcp-adapters pattern: spawn the MCP server as a subprocess over
stdio, open a session, and convert its tool list into LangChain Tool
objects with `load_mcp_tools`.

Kept as an async context manager so callers open one MCP session per
request (simple and correct for a demo; a production app would keep a
long-lived session/pool instead of spawning a subprocess per call).
"""
import os
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..")


@asynccontextmanager
async def mcp_db_tools():
    """Yields the list of LangChain-compatible tools exposed by the
    hotel-workforce-db MCP server (get_schema_glossary, run_metric_query)."""
    params = StdioServerParameters(
        command="python3",
        args=["-m", "app.mcp_server.db_mcp_server"],
        cwd=BACKEND_DIR,
        # mcp's stdio_client does NOT inherit the parent process's
        # environment by default (it sandboxes to a small allowlist for
        # security) — without this, DATABASE_URL/OPENAI_API_KEY etc. are
        # invisible to the subprocess and it silently falls back to
        # whatever database.py's default is.
        env=os.environ.copy(),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            yield tools
