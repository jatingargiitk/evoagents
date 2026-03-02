"""Pipeline runtime — sequential execution of skills with tool calling."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from evoagents.core.config import EvoAgentsConfig
from evoagents.core.skill import SkillRegistry
from evoagents.core.store import RunRecord, TraceStore
from evoagents.providers.base import BaseLLM, LLMResponse
from evoagents.providers.registry import build_providers
from evoagents.scoring.evaluator import evaluate_trace
from evoagents.tools.registry import ToolRegistry

_WEB_SEARCH_NAMES = {"web_search", "web.search"}


class PipelineRunner:
    """Executes a configured pipeline of skills sequentially."""

    def __init__(self, cfg: EvoAgentsConfig):
        self.cfg = cfg
        self.skills = SkillRegistry(cfg.skills_dir)
        self.tools = ToolRegistry()
        self.providers = build_providers(cfg.models)
        self.executor: BaseLLM = self.providers["executor"]

    async def run(self, question: str) -> RunRecord:
        store = TraceStore(self.cfg.store.path)
        run_id = TraceStore.new_run_id()

        trace: dict[str, Any] = {
            "question": question,
            "pipeline": [step.name for step in self.cfg.pipeline],
            "steps": {},
            "tool_calls": [],
            "evidence": {},
        }

        context: dict[str, Any] = {"question": question}

        for step_cfg in self.cfg.pipeline:
            skill = self.skills.get(step_cfg.skill)

            # Make current evidence available to downstream steps.
            context["evidence"] = trace.get("evidence", {})

            step_input = dict(context)
            step_result = await self._execute_step(
                skill_name=skill.name,
                prompt=skill.compile_prompt(),
                allowed_tools=skill.tools.tools,
                context=context,
                question=question,
                trace=trace,
            )

            trace["steps"][step_cfg.name] = {
                "skill": skill.name,
                "version": skill.active_version,
                "input": step_input,
                "output": step_result,
            }

            context[step_cfg.name] = step_result

        judge_provider = self.providers.get("judge", self.executor)
        eval_result = await evaluate_trace(
            question=question,
            trace=trace,
            skills=self.skills.all(),
            provider=judge_provider,
        )

        trace["eval"] = {
            "score": eval_result.score,
            "tags": eval_result.tags,
            "per_skill": [
                {
                    "skill": se.skill,
                    "score": se.score,
                    "tags": se.tags,
                    "failures": se.failures,
                }
                for se in eval_result.per_skill
            ],
        }

        record = RunRecord(
            run_id=run_id,
            ts=time.time(),
            question=question,
            trace_json=trace,
            rule_score=eval_result.score,
            rule_tags=eval_result.tags,
        )
        store.save_run(record)
        return record

    async def run_from_step(
        self,
        question: str,
        trace: dict[str, Any],
        start_step: str,
        patched_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Re-run the pipeline from a specific step onward, using stored intermediate inputs.

        Used by the replay gate for partial replay.
        """
        new_trace: dict[str, Any] = {
            "question": question,
            "pipeline": trace["pipeline"],
            "steps": {},
            "tool_calls": [],
            "evidence": dict(trace.get("evidence", {})),
        }

        steps_order = trace["pipeline"]
        start_idx = steps_order.index(start_step) if start_step in steps_order else 0

        context: dict[str, Any] = {"question": question}
        for step_name in steps_order[:start_idx]:
            stored = trace["steps"].get(step_name, {})
            new_trace["steps"][step_name] = stored
            context[step_name] = stored.get("output", {})

        context["evidence"] = new_trace.get("evidence", {})

        for step_name in steps_order[start_idx:]:
            step_cfg = next(
                (s for s in self.cfg.pipeline if s.name == step_name), None
            )
            if step_cfg is None:
                continue

            skill = self.skills.get(step_cfg.skill)
            prompt = skill.compile_prompt()
            if step_name == start_step and patched_prompt:
                prompt = patched_prompt

            context["evidence"] = new_trace.get("evidence", {})
            step_input = dict(context)
            step_result = await self._execute_step(
                skill_name=skill.name,
                prompt=prompt,
                allowed_tools=skill.tools.tools,
                context=context,
                question=question,
                trace=new_trace,
            )

            new_trace["steps"][step_name] = {
                "skill": skill.name,
                "version": skill.active_version,
                "input": step_input,
                "output": step_result,
            }
            context[step_name] = step_result

        return new_trace

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    async def _execute_step(
        self,
        skill_name: str,
        prompt: str,
        allowed_tools: list[str],
        context: dict[str, Any],
        question: str,
        trace: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a single skill step — delegates to Responses API when web search is needed."""
        if self._needs_web_search(allowed_tools):
            return await self._execute_step_with_search(
                skill_name=skill_name,
                prompt=prompt,
                allowed_tools=allowed_tools,
                context=context,
                question=question,
                trace=trace,
            )
        return await self._execute_step_chat(
            skill_name=skill_name,
            prompt=prompt,
            allowed_tools=allowed_tools,
            context=context,
            question=question,
            trace=trace,
        )

    async def _execute_step_chat(
        self,
        skill_name: str,
        prompt: str,
        allowed_tools: list[str],
        context: dict[str, Any],
        question: str,
        trace: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a step using Chat Completions with function-calling tools."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": self._build_user_message(question, context)},
        ]

        tool_schemas = self.tools.get_schemas(allowed_tools) if allowed_tools else None

        max_iterations = self.cfg.runtime.max_steps
        response: LLMResponse | None = None
        for _ in range(max_iterations):
            response = await self.executor.complete(
                messages=messages,
                tools=tool_schemas,
            )

            if not response.tool_calls:
                return self._parse_output(response.content)

            for tc in response.tool_calls:
                canonical_name = self.tools.resolve_api_name(tc.tool_name)
                result = await self.tools.execute(canonical_name, tc.arguments)

                trace["tool_calls"].append({
                    "tool": canonical_name,
                    "args": tc.arguments,
                    "ok": result.ok,
                    "latency_ms": result.latency_ms,
                })

                if result.ok and result.data:
                    evidence_key = f"e{len(trace['evidence']) + 1}"
                    trace["evidence"][evidence_key] = {
                        "source": canonical_name,
                        "payload": result.data,
                    }

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tc.call_id or f"call_{tc.tool_name}",
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.call_id or f"call_{tc.tool_name}",
                    "content": json.dumps(
                        result.data if result.ok else {"error": result.error}
                    ),
                })

        return self._parse_output(response.content if response else "")

    async def _execute_step_with_search(
        self,
        skill_name: str,
        prompt: str,
        allowed_tools: list[str],
        context: dict[str, Any],
        question: str,
        trace: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a step using OpenAI Responses API with native web search.

        After gathering search results, does a follow-up Chat Completions call
        to format the output as the structured JSON the skill requires.
        """
        import os

        from openai import AsyncOpenAI

        api_key = getattr(self.executor, "api_key", None) or os.environ.get(
            "OPENAI_API_KEY", ""
        )
        model = self.executor.model_name

        client = AsyncOpenAI(api_key=api_key)

        tools: list[dict[str, Any]] = [
            {"type": "web_search", "search_context_size": "medium"},
        ]

        non_search_tools = [t for t in (allowed_tools or []) if t not in _WEB_SEARCH_NAMES]
        if non_search_tools:
            for schema in self.tools.get_schemas(non_search_tools):
                tools.append({
                    "type": "function",
                    "name": schema.name,
                    "description": schema.description,
                    "parameters": schema.parameters,
                    "strict": False,
                })

        input_items: list[dict[str, Any]] = [
            {"role": "developer", "content": prompt},
            {"role": "user", "content": self._build_user_message(question, context)},
        ]

        response = await client.responses.create(
            model=model,
            input=input_items,
            tools=tools,
            temperature=0.7,
        )

        max_iterations = self.cfg.runtime.max_steps
        for _ in range(max_iterations):
            self._collect_search_evidence(response, trace)

            function_calls = [
                item for item in response.output if item.type == "function_call"
            ]
            if not function_calls:
                break

            func_outputs: list[dict[str, Any]] = []
            for fc in function_calls:
                args = json.loads(fc.arguments) if isinstance(fc.arguments, str) else fc.arguments
                canonical_name = self.tools.resolve_api_name(fc.name)
                result = await self.tools.execute(canonical_name, args)

                trace["tool_calls"].append({
                    "tool": canonical_name,
                    "args": args,
                    "ok": result.ok,
                    "latency_ms": result.latency_ms,
                })

                if result.ok and result.data:
                    evidence_key = f"e{len(trace['evidence']) + 1}"
                    trace["evidence"][evidence_key] = {
                        "source": canonical_name,
                        "payload": result.data,
                    }

                func_outputs.append({
                    "type": "function_call_output",
                    "call_id": fc.call_id,
                    "output": json.dumps(
                        result.data if result.ok else {"error": str(result.error)}
                    ),
                })

            response = await client.responses.create(
                model=model,
                previous_response_id=response.id,
                input=func_outputs,
            )

        # Extract the prose research summary from the Responses API
        research_text = self._extract_response_text(response)
        real_urls = self._extract_annotation_urls(response)

        # If it already parses as JSON, we're done
        parsed = self._parse_output(research_text)
        if "text" not in parsed:
            return parsed

        # Otherwise, do a follow-up Chat call to reformat as the required JSON structure
        return await self._reformat_as_json(
            research_text=research_text,
            prompt=prompt,
            question=question,
            real_urls=real_urls,
        )

    async def _reformat_as_json(
        self,
        research_text: str,
        prompt: str,
        question: str,
        real_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        """Follow-up Chat Completions call to convert research prose into required JSON."""
        url_hint = ""
        if real_urls:
            url_list = "\n".join(f"- {u}" for u in real_urls)
            url_hint = (
                f"\n\nREAL SOURCE URLS from web search (use these exactly in the "
                f"'sources' field — do NOT invent or modify URLs):\n{url_list}"
            )

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    f"{prompt}\n\n"
                    "You have already completed the research. "
                    "Now format the findings as the JSON structure "
                    "specified in your Output Format section. "
                    "Respond with ONLY the JSON object — no markdown fences, no prose."
                    f"{url_hint}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    f"Research findings to format:\n{research_text}"
                ),
            },
        ]
        response = await self.executor.complete(
            messages=messages, temperature=0.2, max_tokens=16384
        )
        return self._parse_output(response.content)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _needs_web_search(allowed_tools: list[str]) -> bool:
        return bool(set(allowed_tools or []) & _WEB_SEARCH_NAMES)

    @staticmethod
    def _extract_annotation_urls(response: Any) -> list[str]:
        """Extract real source URLs from Responses API annotation objects."""
        urls: list[str] = []
        seen: set[str] = set()
        for item in response.output:
            if item.type == "message":
                for part in item.content:
                    for ann in getattr(part, "annotations", []) or []:
                        url = getattr(ann, "url", None)
                        if url and url not in seen:
                            seen.add(url)
                            urls.append(url)
        return urls

    @staticmethod
    def _collect_search_evidence(response: Any, trace: dict[str, Any]) -> None:
        """Record web search calls and URL annotations from Responses API output."""
        seen_urls: set[str] = set()
        for item in response.output:
            if item.type == "web_search_call":
                trace["tool_calls"].append({
                    "tool": "web.search",
                    "args": {},
                    "ok": True,
                    "latency_ms": 0,
                })
            elif item.type == "message":
                for part in item.content:
                    for ann in getattr(part, "annotations", []) or []:
                        url = getattr(ann, "url", None)
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            evidence_key = f"e{len(trace['evidence']) + 1}"
                            trace["evidence"][evidence_key] = {
                                "source": "web.search",
                                "payload": {
                                    "url": url,
                                    "title": getattr(ann, "title", ""),
                                },
                            }

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        """Pull final text from a Responses API response object."""
        parts: list[str] = []
        for item in response.output:
            if item.type == "message":
                for part in item.content:
                    text = getattr(part, "text", None)
                    if text:
                        parts.append(text)
        return "\n".join(parts)

    def _build_user_message(self, question: str, context: dict[str, Any]) -> str:
        parts = [f"Question: {question}"]
        for key, val in context.items():
            if key == "question":
                continue
            parts.append(f"\n--- {key} output ---\n{json.dumps(val, indent=2)}")
        return "\n".join(parts)

    @staticmethod
    def _parse_output(content: str) -> dict[str, Any]:
        """Try to parse the LLM output as JSON; fall back to text wrapper."""
        content = content.strip()

        # Direct JSON object
        if content.startswith("{"):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass

        # Fenced block at start (```json ... ``` or ``` ... ```)
        if content.startswith("```"):
            lines = content.split("\n")
            inner = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()
            try:
                return json.loads(inner)
            except (json.JSONDecodeError, ValueError):
                pass

        # Embedded fence anywhere in prose (e.g. "Here are results:\n```json\n{...}\n```")
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # Last resort: find any {...} block in the content
        brace_match = re.search(r"\{.*\}", content, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except (json.JSONDecodeError, ValueError):
                pass

        return {"text": content}
