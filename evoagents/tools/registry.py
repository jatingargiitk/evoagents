"""Tool registry — manages built-in and custom tools."""

from __future__ import annotations

from typing import Any

from evoagents.providers.base import ToolSchema
from evoagents.tools.base import BaseTool, ToolResult
from evoagents.tools.http_get import HttpGetTool


class ToolRegistry:
    """Registry of available tools with allowlist enforcement.

    Web search is handled natively by the OpenAI Responses API,
    so only non-search tools (e.g. http_get) are registered here.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._api_name_map: dict[str, str] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        self.register(HttpGetTool())

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        self._api_name_map[tool.api_name] = tool.name

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def resolve_api_name(self, api_name: str) -> str:
        """Map an LLM-returned api_name back to the user-facing tool name."""
        return self._api_name_map.get(api_name, api_name)

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            canonical = self.resolve_api_name(name)
            tool = self.get(canonical)
        if tool is None:
            return ToolResult(ok=False, error=f"Unknown tool: {name}", latency_ms=0)
        return await tool.execute(arguments)

    def get_schemas(self, allowed_tools: list[str] | None = None) -> list[ToolSchema]:
        """Return ToolSchema objects for tools in the allowlist.

        Uses api_name (underscore-safe) for the schema name sent to LLMs.
        Accepts both canonical names (http.get) and api names (http_get).
        """
        schemas = []
        for name, tool in self._tools.items():
            if allowed_tools is not None:
                if name not in allowed_tools and tool.api_name not in allowed_tools:
                    continue
            schemas.append(ToolSchema(
                name=tool.api_name,
                description=tool.description,
                parameters=tool.parameters_schema,
            ))
        return schemas

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
