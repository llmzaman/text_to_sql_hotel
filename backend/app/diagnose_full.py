"""
Second diagnostic: runs the REAL graph (MCP + local tools) on one question
and prints every message, so we can see whether tool calls fire through
the full pipeline — not just an isolated bind_tools.

Usage: python -m app.diagnose_full
"""
import asyncio, os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from app.agents.graph import build_agent
from app.agents.mcp_client import mcp_db_tools


async def main():
    async with mcp_db_tools() as mcp_tools:
        print("MCP tools loaded:", [t.name for t in mcp_tools])
        for t in mcp_tools:
            print(f"  - {t.name} args_schema:", getattr(t, "args", "NONE"))

        agent = build_agent(mcp_tools, role="supervisor", hotel_id=1, hotel_name="Grand Meridian Hotel")
        result = await agent.ainvoke({
            "messages": [HumanMessage(content="How many total hours were worked this week?")]
        })

        print("\n--- message trace ---")
        for m in result["messages"]:
            kind = type(m).__name__
            tc = getattr(m, "tool_calls", None)
            print(f"[{kind}] tool_calls={tc!r}")
            if getattr(m, "content", None):
                print("   content:", repr(m.content)[:200])


if __name__ == "__main__":
    asyncio.run(main())