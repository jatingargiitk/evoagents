"""Abstract base classes for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRequest:
    tool_name: str
    arguments: dict[str, Any]
    call_id: str = ""


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]


class BaseLLM(ABC):
    """Abstract LLM provider interface."""

    @property
    def model_name(self) -> str:
        return "unknown"

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> LLMResponse:
        ...

    @abstractmethod
    def provider_name(self) -> str:
        ...
