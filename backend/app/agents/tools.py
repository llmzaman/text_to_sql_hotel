"""
Local (non-MCP) LangChain tools used alongside the MCP database tools.

- search_policy_documents: the RAG half of the system — retrieves relevant
  chunks from the synthetic SOP/HR/labor/contract PDFs.
- emit_chart: lets the agent explicitly request a chart be rendered in the
  UI. The agent calls this with structured data instead of trying to draw
  ASCII charts in text; the backend intercepts the tool call and forwards
  the chart spec to the frontend, which renders it with Chart.js.
"""
import json
from typing import List, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.rag.vectorstore import RagIndex


@tool
def search_policy_documents(query: str) -> str:
    """Search the agency's policy and SOP documents (cleaning checklist SOP,
    HR leave policy, labor hours & overtime compliance policy, hotel
    contract SLA summary) for relevant passages. Use this for questions
    about rules, thresholds, procedures, or compliance — e.g. 'what's the
    max hours a worker can be scheduled per day' or 'when does a cleaner
    get flagged for repeated failed inspections'. Do NOT use this for
    questions about actual current numbers (use run_metric_query instead)."""
    idx = RagIndex.get()
    results = idx.search(query, k=4)
    if not results:
        return "No relevant policy passages found."
    formatted = []
    for r in results:
        formatted.append(f"[{r['doc_title']}, {r['section']}]\n{r['text']}")
    return "\n\n---\n\n".join(formatted)


class ChartSpec(BaseModel):
    chart_type: Literal["bar", "line", "pie"] = Field(description="Type of chart to render")
    title: str = Field(description="Short chart title")
    labels: List[str] = Field(description="X-axis labels or category names")
    values: List[float] = Field(description="Numeric values, same length and order as labels")
    series_label: str = Field(default="Value", description="Label for the value series, e.g. 'Hours worked'")


@tool
def emit_chart(chart_type: str, title: str, labels: List[str], values: List[float], series_label: str = "Value") -> str:
    """Request a chart be shown to the user in the UI, on top of your text
    answer. You MUST call this — not just format a markdown table or bullet
    list — whenever the answer involves 3+ comparable numbers: a ranking
    ('top N workers/clients'), a comparison across clients/workers, or a
    trend over time ('hours trend', 'this week vs last week'). If a
    question compares multiple different metrics at once (e.g. hours AND
    headcount AND absentee rate across clients), call this once per metric
    — one chart per distinct unit/series, not one chart trying to cram
    unrelated metrics together. chart_type must be one of 'bar' (rankings/
    comparisons), 'line' (trends over time), or 'pie' (part-of-whole).
    labels and values must be the same length. Skip this only for a single
    number with no ranking/comparison (e.g. 'what's our absentee rate')."""
    spec = ChartSpec(chart_type=chart_type, title=title, labels=labels, values=values, series_label=series_label)
    return json.dumps({"status": "chart_queued", "spec": spec.model_dump()})


LOCAL_TOOLS = [search_policy_documents, emit_chart]
