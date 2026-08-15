"""
Explicit LangGraph agent loop (replaces langgraph's prebuilt
create_react_agent, which silently failed to bind tools in this
environment). This builds the same graph by hand: an LLM node that
decides which tool to call, a tool-execution node, looped until the
model stops requesting tools — then the final LLM message is the answer.

We call llm.bind_tools(...) directly here, which is the exact call the
diagnostic confirmed works reliably, so tools reliably reach the model
as real function definitions.

Both OpenAI and Groq are wired up; LLM_PROVIDER picks which one runs
(defaults to "openai"). Groq's free/on-demand tier caps out at a low
shared tokens-per-minute budget (6-12k TPM across the account) and its
smaller/free-tier models were unreliable at real tool-calling (silently
echoing the call as text instead of invoking it) — OpenAI has much higher
default rate limits and solid tool-calling, hence the default.
"""
import os
from typing import Annotated, TypedDict

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from app.agents.tools import LOCAL_TOOLS

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")


def _build_llm():
    if LLM_PROVIDER == "groq":
        return ChatGroq(model=GROQ_MODEL, temperature=0.2, max_retries=4)
    return ChatOpenAI(model=OPENAI_MODEL, temperature=0.2, max_retries=4)


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def _system_prompt(role: str, client_id, client_name, supervisor_id=None) -> str:
    if role == "supervisor":
        scope = (
            f"You are assisting a CLIENT SUPERVISOR at '{client_name}' (client_id={client_id}). "
            f"They can only see data for their own client. Always pass client_id={client_id} and "
            f"role='supervisor' to run_metric_query. Never answer questions about other clients — "
            f"politely explain that's outside their access if asked."
        )
    elif role == "team_supervisor":
        scope = (
            f"You are assisting a SUPERVISOR (supervisor_id={supervisor_id}) who oversees a specific "
            f"set of clients assigned to them via the supervisor_client table — NOT all clients. "
            f"Always pass role='team_supervisor' and supervisor_id={supervisor_id} to run_metric_query. "
            + (
                f"They've currently selected client '{client_name}' (client_id={client_id}) — pass that "
                f"client_id too unless they ask about all their clients together."
                if client_id is not None
                else "No single client is selected — omit client_id to aggregate across all clients "
                     "assigned to this supervisor."
            )
            + " Never answer questions about clients outside this supervisor's assignments."
        )
    else:
        scope = (
            "You are assisting the HEAD OF SUPERVISORS, who oversees all clients in the agency. "
            "Always pass role='head_supervisor' to run_metric_query. Omit client_id to aggregate "
            "across all clients, or pass a specific client_id when the question is about one client."
        )

    return f"""You are a business intelligence assistant for a cleaning workforce
management platform. {scope}

You have three kinds of tools:
1. get_schema_glossary / run_metric_query — for ANY question involving numbers: hours,
   headcount, absenteeism, inspection pass rates, top workers, overtime, trends. Call
   get_schema_glossary first if unsure which metric name fits, then run_metric_query.
   Never invent numbers — always call the tool.
2. search_policy_documents — for questions about rules, policy, SOPs, compliance
   thresholds, or contract terms (not for current numbers).
3. emit_chart — call whenever a ranking, comparison, or trend over time would be clearer
   as a chart. 'bar' for rankings/comparisons, 'line' for trends, 'pie' for part-of-whole.

Answer concisely, like a sharp operations analyst. Lead with the number/insight. When a
question needs both a policy check and current numbers, use both tool types before answering.

You MUST use the real tool-calling mechanism to call tools. NEVER write a tool name or its
JSON arguments as text in your reply — that does not run anything and the user sees no data.
After the tools return, write a natural-language answer using their results.

If a tool returns an "error" field, quote that exact error message to the user instead of
guessing or inventing a plausible-sounding cause — an invented explanation is actively
misleading. If retrying with corrected arguments won't help, just report the error verbatim."""


def build_agent(mcp_tools, role: str, client_id, client_name, supervisor_id=None):
    all_tools = list(mcp_tools) + LOCAL_TOOLS
    tools_by_name = {t.name: t for t in all_tools}

    llm = _build_llm()
    llm_with_tools = llm.bind_tools(all_tools)
    system = SystemMessage(content=_system_prompt(role, client_id, client_name, supervisor_id))

    async def call_model(state: AgentState):
        resp = await llm_with_tools.ainvoke([system] + state["messages"])
        return {"messages": [resp]}

    async def call_tools(state: AgentState):
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            tool = tools_by_name.get(tc["name"])
            if tool is None:
                results.append(ToolMessage(
                    content=f"Error: unknown tool {tc['name']}", tool_call_id=tc["id"], name=tc["name"]))
                continue
            try:
                output = await tool.ainvoke(tc["args"])
            except Exception as e:
                output = f"Error running {tc['name']}: {e}"
            results.append(ToolMessage(content=str(output), tool_call_id=tc["id"], name=tc["name"]))
        return {"messages": results}

    def should_continue(state: AgentState):
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(AgentState)
    graph.add_node("model", call_model)
    graph.add_node("tools", call_tools)
    graph.set_entry_point("model")
    graph.add_conditional_edges("model", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")
    return graph.compile()