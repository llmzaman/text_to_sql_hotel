from typing import List, Literal, Optional
from pydantic import BaseModel


class ClientOut(BaseModel):
    client_id: int
    name: str
    city: Optional[str] = None
    room_count: Optional[int] = None


class SupervisorOut(BaseModel):
    supervisor_id: int
    name: str


class ChatTurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str
    user_role: Literal["supervisor", "team_supervisor", "head_supervisor"]
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    supervisor_id: Optional[int] = None
    history: List[ChatTurnIn] = []


class ChartSpecOut(BaseModel):
    chart_type: str
    title: str
    labels: List[str]
    values: List[float]
    series_label: str


class ChatResponse(BaseModel):
    answer: str
    chart: Optional[ChartSpecOut] = None
    tools_used: List[str] = []


class DashboardRequest(BaseModel):
    user_role: Literal["supervisor", "team_supervisor", "head_supervisor"]
    client_id: Optional[int] = None
    supervisor_id: Optional[int] = None
    days: int = 7
