"""Anthropic LLM provider implementation."""

from __future__ import annotations

import os
from typing import Any

from evoagents.providers.base import BaseLLM, LLMResponse, ToolCallRequest, ToolSchema


class AnthropicProvider(BaseLLM):
    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

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
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self.api_key)

        system_msg = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_messages.append(m)

        if not user_messages:
            user_messages = [{"role": "user", "content": "Continue."}]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": user_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_msg:
            kwargs["system"] = system_msg

        if tools:
            kwargs["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]

        response = await client.messages.create(**kwargs)

        content_text = ""
        tool_calls: list[ToolCallRequest] = []

        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCallRequest(
                    tool_name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                    call_id=block.id,
                ))

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            },
            raw=response,
        )

    def provider_name(self) -> str:
        return "anthropic"
