"""
Standalone check: does ChatGroq actually invoke tools via real function
calling, independent of MCP/LangGraph? Run this after the mcp_server fix
to confirm the root cause before re-testing the full app.

Usage (from backend/, venv active, GROQ_API_KEY set in .env or exported):
    python -m app.diagnose_tool_calling
"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq


@tool
def run_metric_query(metric: str, role: str, hotel_id: int | None = None, days: int = 7) -> str:
    """Run a business metric query. metric: e.g. 'total_hours_by_hotel'.
    role: 'supervisor' or 'head_supervisor'. hotel_id: optional int."""
    return f"[FAKE RESULT] metric={metric} role={role} hotel_id={hotel_id} days={days}: 1533 hours"


def main():
    if not os.environ.get("GROQ_API_KEY"):
        print("GROQ_API_KEY not set — export it or put it in backend/.env first.")
        return

    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    print(f"Using model: {model}")

    llm = ChatGroq(model=model, temperature=0)
    llm_with_tools = llm.bind_tools([run_metric_query])

    resp = llm_with_tools.invoke([
        HumanMessage(content="How many total hours were worked this week for hotel_id=1, role=supervisor?")
    ])

    print("\n--- raw response ---")
    print("content:", repr(resp.content))
    print("tool_calls:", resp.tool_calls)

    if resp.tool_calls:
        print("\nPASS: the model made a real tool call. Function calling works.")
        print("If the full app still narrates JSON instead of calling tools,")
        print("the bug is in how tools are assembled/passed in agents/graph.py,")
        print("not in ChatGroq or the Groq account/model itself.")
    else:
        print("\nFAIL: the model did NOT make a tool call — it just answered in text.")
        print("This confirms the problem is upstream of your app: either the")
        print(f"model '{model}' doesn't reliably use tool calling, or the")
        print("installed langchain-groq version has a tool-binding issue.")
        print("Try: pip install -U langchain-groq, or switch GROQ_MODEL to")
        print("another tool-calling-capable model from https://console.groq.com/docs/models")


if __name__ == "__main__":
    main()