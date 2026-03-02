"""Base classes for the tool system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    latency_ms: int = 0
    error: str | None = None


class BaseTool(ABC):
    """Abstract tool that skills can invoke."""

    @property
    @abstractmethod
    def name(self) -> str:
        """User-facing name (e.g. 'web.search'). Used in config, traces, and logs."""
        ...

    @property
    def api_name(self) -> str:
        """LLM-safe name (dots replaced with underscores) for function-calling APIs."""
        return self.name.replace(".", "_")

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        ...

    @abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ...
