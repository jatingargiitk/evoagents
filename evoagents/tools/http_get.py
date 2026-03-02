"""http.get tool — real HTTP GET via httpx."""

from __future__ import annotations

import time
from typing import Any

from evoagents.tools.base import BaseTool, ToolResult


class HttpGetTool(BaseTool):

    @property
    def name(self) -> str:
        return "http.get"

    @property
    def description(self) -> str:
        return "Fetch a URL via HTTP GET. Returns status code, headers, and body text."

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch.",
                },
            },
            "required": ["url"],
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        url = arguments.get("url", "")
        start = time.monotonic()
        try:
            import httpx

            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(url, timeout=15.0)
                latency = int((time.monotonic() - start) * 1000)
                body = resp.text[:10000]

                return ToolResult(
                    ok=resp.is_success,
                    data={
                        "url": url,
                        "status": resp.status_code,
                        "body": body,
                        "headers": dict(resp.headers),
                    },
                    latency_ms=latency,
                )
        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            return ToolResult(ok=False, error=str(e), latency_ms=latency)
