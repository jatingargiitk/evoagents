"""OpenAI LLM provider implementation."""

from __future__ import annotations

import os
from typing import Any

from evoagents.providers.base import BaseLLM, LLMResponse, ToolCallRequest, ToolSchema


class OpenAIProvider(BaseLLM):
    def __init__(self, model: str = "gpt-4o", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    @property
    def model_name(self) -> str:
        return self.model

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key)

        # Reasoning / GPT-5.x models use max_completion_tokens and don't support temperature
        _is_reasoning = (
            self.model.startswith("o1")
            or self.model.startswith("o3")
            or self.model.startswith("o4")
            or self.model.startswith("gpt-5")
        )

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens" if _is_reasoning else "max_tokens": max_tokens,
        }
        if not _is_reasoning:
            kwargs["temperature"] = temperature

        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCallRequest] = []
        if message.tool_calls:
            import json

            for tc in message.tool_calls:
                tool_calls.append(ToolCallRequest(
                    tool_name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                    call_id=tc.id,
                ))

        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
            raw=response,
        )

    def provider_name(self) -> str:
        return "openai"
