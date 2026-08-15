"""
Entry point called by the FastAPI /chat endpoint. Opens an MCP session,
builds the agent, runs it on the conversation, and extracts:
  - the final natural-language answer
  - any chart the agent requested via emit_chart
  - which tools were used (surfaced in the UI as a small "how I got this" trace)
"""
import json
from typing import List, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.graph import build_agent
from app.agents.mcp_client import mcp_db_tools


class ChatTurn(TypedDict):
    role: str  # "user" | "assistant"
    content: str


async def answer_question(
    question: str,
    role: str,
    client_id: Optional[int],
    client_name: Optional[str],
    history: List[ChatTurn],
    supervisor_id: Optional[int] = None,
):
    messages = []
    for turn in history[-6:]:  # keep last few turns for context, bound token usage
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        else:
            messages.append(AIMessage(content=turn["content"]))
    messages.append(HumanMessage(content=question))

    async with mcp_db_tools() as mcp_tools:
        agent = build_agent(mcp_tools, role, client_id, client_name, supervisor_id)
        result = await agent.ainvoke({"messages": messages})

    out_messages = result["messages"]
    final_answer = ""
    chart = None
    tools_used = []

    for m in out_messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                tools_used.append(tc["name"])
        if isinstance(m, ToolMessage) and m.name == "emit_chart":
            try:
                payload = json.loads(m.content)
                chart = payload.get("spec")
            except (json.JSONDecodeError, AttributeError):
                pass

    # last AI message with actual text content is the synthesized answer
    for m in reversed(out_messages):
        if isinstance(m, AIMessage) and m.content:
            final_answer = m.content if isinstance(m.content, str) else str(m.content)
            break

    return {
        "answer": final_answer or "I wasn't able to produce an answer for that.",
        "chart": chart,
        "tools_used": sorted(set(tools_used)),
    }
