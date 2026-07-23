from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


@dataclass(slots=True)
class RuntimeResponse:
    status_code: int
    body: Any
    headers: dict[str, str]
    elapsed_ms: float


class RuntimeCapabilities(BaseModel):
    runtime: str
    stateful_scenarios: bool = True
    request_journal: bool = True
    delays: bool = True
    global_reset: bool = True
    persistent: bool = False
    storage: str = "external"
    journal_limit: int | None = None


class RuntimeValueMatcher(BaseModel):
    equal_to: str | None = None
    absent: bool = False


class RuntimeRequestMatcher(BaseModel):
    method: str
    path: str | None = None
    path_pattern: str | None = None
    query: dict[str, RuntimeValueMatcher] = Field(default_factory=dict)
    headers: dict[str, RuntimeValueMatcher] = Field(default_factory=dict)
    match_body: bool = False
    json_body: Any = None


class RuntimeResponseDefinition(BaseModel):
    status: int
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: Any = None
    delay_ms: int = 0


class RuntimeMapping(BaseModel):
    name: str
    priority: int = 10
    request: RuntimeRequestMatcher
    response: RuntimeResponseDefinition
    metadata: dict[str, Any] = Field(default_factory=dict)
    scenario_name: str | None = None
    required_state: str | None = None
    new_state: str | None = None
