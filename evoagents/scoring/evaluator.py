"""Per-skill LLM evaluator — evaluates each skill independently."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from evoagents.providers.base import BaseLLM

SKILL_EVAL_SYSTEM = """\
You are a strict evaluator for a single agent skill. You will receive:
1. The user's original question
2. The skill's constraints, tool rules, and output format
3. The skill's actual output
4. Context from upstream steps (if any)

Evaluate whether the skill followed its constraints and produced good output.

## Rules
- If a constraint says MUST and the skill didn't do it, that's a failure.
- If a constraint says NEVER and the skill did it, that's a failure.
- If the skill had tools available but didn't use them when needed, that's a failure.
- Be strict but fair.

## Important: Web Search
`web.search({})` in the Tool Calls list means the skill used OpenAI's native built-in
web search (Responses API). This is FULLY equivalent to an explicit function call to
web_search. If you see `web.search({}) -> OK`, the skill DID successfully search the web.
Do NOT penalize this as "no tool calls" or "no function calling".

## Important: Skills with no tools
If `Available Tools` is "none", the skill has NO tools at all. NEVER flag it for
"no tool calls", "did not use web search", or any tool-related failure. Ignore all
tool-use criteria entirely for such skills.

## Important: "At least N" constraints
When a constraint says "at least 3" of something (e.g. sources, findings, points),
providing MORE than the minimum is always acceptable. NEVER penalize a skill for
exceeding a minimum requirement. Only penalize if the output has FEWER than required.

## Output
Respond with ONLY this JSON — no other text:
{
  "score": 0.0,
  "tags": ["skill_name.failure_type"],
  "failures": [
    {"tag": "skill_name.failure_type", "reason": "one-line explanation"}
  ]
}

Scoring:
- 1.0 = all constraints followed, good output
- 0.0 = critical violations
- Deduct 0.2-0.3 per violated MUST constraint

Tag format: skill_name.failure_type
Examples: planner.no_tool_calls, synthesizer.missing_citations, perception.bad_format
"""

SKILL_EVAL_USER = """\
Question: {question}

Skill: {skill_name}

Constraints:
{constraints}

Tool Rules:
{tool_rules}

Expected Output Format:
{output_format}

Available Tools: {available_tools}

{upstream_context}

Actual Output:
```json
{actual_output}
```

Tool Calls Made: {tool_calls}

Evaluate this skill's output. Respond with ONLY the JSON.
"""


@dataclass
class SkillEval:
    """Evaluation result for a single skill."""
    skill: str
    score: float
    tags: list[str] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)


@dataclass
class EvalResult:
    """Aggregate evaluation across all skills."""
    score: float
    tags: list[str] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    per_skill: list[SkillEval] = field(default_factory=list)


async def evaluate_trace(
    question: str,
    trace: dict[str, Any],
    skills: dict[str, Any],
    provider: BaseLLM,
) -> EvalResult:
    """Evaluate a pipeline trace by evaluating each skill independently."""
    steps = trace.get("steps", {})
    step_order = trace.get("pipeline", list(steps.keys()))
    tool_calls = trace.get("tool_calls", [])

    per_skill: list[SkillEval] = []
    prev_outputs: dict[str, Any] = {}

    for step_name in step_order:
        step_data = steps.get(step_name)
        if step_data is None:
            continue

        skill_name = step_data.get("skill", step_name)
        skill = skills.get(skill_name)
        if skill is None:
            continue

        step_tool_calls = [
            tc for tc in tool_calls
            if _tool_belongs_to_skill(tc, skill)
        ]

        result = await evaluate_single_skill(
            question=question,
            skill_name=skill_name,
            skill=skill,
            step_output=step_data.get("output", {}),
            tool_calls=step_tool_calls,
            upstream_outputs=dict(prev_outputs),
            provider=provider,
        )
        per_skill.append(result)
        prev_outputs[step_name] = step_data.get("output", {})

    return _aggregate(per_skill)


async def evaluate_single_skill(
    question: str,
    skill_name: str,
    skill: Any,
    step_output: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    upstream_outputs: dict[str, Any],
    provider: BaseLLM,
) -> SkillEval:
    """Evaluate a single skill's output against its constraints."""
    s = skill.sections

    upstream_text = ""
    if upstream_outputs:
        parts = []
        for name, output in upstream_outputs.items():
            parts.append(f"--- {name} output ---\n{json.dumps(output, indent=2)}")
        upstream_text = "Upstream Context:\n" + "\n".join(parts)

    tc_text = "(none)"
    if tool_calls:
        lines = []
        for tc in tool_calls:
            status = "OK" if tc.get("ok") else "FAILED"
            lines.append(f"- {tc.get('tool', '?')}({json.dumps(tc.get('args', {}))}) -> {status}")
        tc_text = "\n".join(lines)

    messages = [
        {"role": "system", "content": SKILL_EVAL_SYSTEM},
        {
            "role": "user",
            "content": SKILL_EVAL_USER.format(
                question=question,
                skill_name=skill_name,
                constraints=s.constraints or "(none defined)",
                tool_rules=s.tools or "(none defined)",
                output_format=s.output_format or "(none defined)",
                available_tools=(
                    ", ".join(skill.tools.tools) if skill.tools.tools else "none"
                ),
                upstream_context=upstream_text,
                actual_output=json.dumps(step_output, indent=2),
                tool_calls=tc_text,
            ),
        },
    ]

    response = await provider.complete(
        messages=messages, temperature=0.1, max_tokens=512
    )
    return _parse_skill_eval(response.content, skill_name)


def _tool_belongs_to_skill(
    tool_call: dict[str, Any], skill: Any
) -> bool:
    """Check if a tool call belongs to a skill based on its allowed tools."""
    tool_name = tool_call.get("tool", "")
    allowed = skill.tools.tools if skill.tools else []
    if not allowed:
        return False
    api_name = tool_name.replace(".", "_")
    return tool_name in allowed or api_name in allowed


def _parse_skill_eval(content: str, skill_name: str) -> SkillEval:
    """Parse LLM response into a SkillEval."""
    json_match = re.search(r"\{.*\}", content, re.DOTALL)
    if not json_match:
        return SkillEval(skill=skill_name, score=0.5)

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        return SkillEval(skill=skill_name, score=0.5)

    score = max(0.0, min(1.0, float(data.get("score", 0.5))))

    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t) for t in tags if isinstance(t, str)]

    failures = data.get("failures", [])
    if not isinstance(failures, list):
        failures = []

    return SkillEval(
        skill=skill_name,
        score=score,
        tags=tags,
        failures=failures,
    )


def _aggregate(per_skill: list[SkillEval]) -> EvalResult:
    """Aggregate per-skill results into an overall EvalResult."""
    if not per_skill:
        return EvalResult(score=1.0)

    all_tags: list[str] = []
    all_failures: list[dict[str, str]] = []
    total_score = 0.0

    for se in per_skill:
        total_score += se.score
        all_tags.extend(se.tags)
        all_failures.extend(se.failures)

    avg_score = total_score / len(per_skill)

    return EvalResult(
        score=round(avg_score, 3),
        tags=all_tags,
        failures=all_failures,
        per_skill=per_skill,
    )
