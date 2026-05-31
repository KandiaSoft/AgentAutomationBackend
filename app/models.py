from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any


class QuestionnaireItem(BaseModel):
    number: int
    question: str
    response: str = ""
    expert_code: str | None = None


class AgentQuestionnaireOption(BaseModel):
    number: int
    question: str
    responses: list[str]
    expert_code: str | None = None


class AgentRequest(BaseModel):
    user_id: str
    thread_id: str
    question: str
    username: str
    interrupt: int
    questionnaire: list[QuestionnaireItem] = []


class TokenUsage(BaseModel):
    in_tokens: int = 0
    out_tokens: int = 0
    model: str = "No model used"


class AgentResponse(BaseModel):
    answer: str
    tokens: list[TokenUsage] = []
    understanding: str = ""
    has_interrupt: bool = False
    status: str = "success"
    short_codes: list[Any] = []
    finished: bool = False
    questionnaire: list[AgentQuestionnaireOption] = []
    is_questionnaire: bool = False
    agent: str | None = None


class SimulationConfig(BaseModel):
    persona_key: str
    scenario_key: str | None = None
    scenario_text: str | None = None
    count: int = Field(default=1, ge=1, le=10)
    delay_ms: list[int] = Field(default=[2000, 6000])
    generate_scenario: bool = False
    language: str = "it"


class SimulationSummary(BaseModel):
    id: str
    thread_id: str
    persona_key: str
    scenario_key: str | None
    initial_request: str
    language: str = "it"
    status: str
    finished: bool
    total_in_tokens: int
    total_out_tokens: int
    turn_count: int
    created_at: str
    finished_at: str | None
    error: str | None
    short_codes: list[Any]


class TurnRecord(BaseModel):
    id: int
    simulation_id: str
    turn_index: int
    role: str
    question: str | None
    answer: str | None
    understanding: str | None
    is_questionnaire: bool
    has_interrupt: bool
    questionnaire: list[Any]
    client_reasoning: str | None
    in_tokens: int
    out_tokens: int
    duration_ms: int | None
    created_at: str


class SimulationDetail(SimulationSummary):
    turns: list[TurnRecord]


class StartResponse(BaseModel):
    simulation_ids: list[str]


class Persona(BaseModel):
    key: str
    label: str
    description: str


class Scenario(BaseModel):
    key: str
    label: str
    text: str
    category: str
