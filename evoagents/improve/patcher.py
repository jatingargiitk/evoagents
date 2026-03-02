"""LLM autopatcher — section-level patching of SKILL.md files."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import yaml

from evoagents.core.skill import Skill, SkillSections, parse_skill_md
from evoagents.providers.base import BaseLLM

PATCHER_SYSTEM = """\
You are an expert prompt engineer. You improve agent skills by adding \
targeted patches to specific sections of a SKILL.md definition.

You will receive the skill's current sections, the actual output that \
failed, and the specific reason it failed. Your job: fix the skill \
definition so this failure won't happen again.

## Patchable Sections
- constraints: MUST/NEVER rules
- tools: Per-tool "When to call" guidance
- output_format: Expected response structure
- examples: Concrete input->output demonstrations

## Rules
- Each patch targets one section with action "add" (append) or "replace".
- For "add", provide ONLY the new lines to append.
- Keep patches minimal. Add 1-2 targeted rules, not a wall of text.
- Preserve existing content unless it directly caused the failure.
- If a failure is about tool usage (e.g., no_tool_calls, skipped_web_search,
  outdated_info), you MUST add constraints that explicitly require a tool
  call and also update Output Format to surface tool usage (e.g., tools_used).
- If a failure is about missing entities or recency handling, you MUST add
  constraints that force inclusion of temporal keywords and all named entities
  from the question in the output.
- If a failure is about citations or grounding, you MUST add explicit citation
  requirements tied to evidence IDs (e.g., [e1], [e2]).

## Critical: Always update Examples to match new constraints
WHENEVER you add or change a constraint about what must appear in the output,
you MUST ALSO include an "examples" patch that demonstrates the new behavior.
If the existing examples show output that contradicts your new constraint,
replace them. LLMs follow examples more reliably than abstract rules — an
inconsistent example silently overrides your new constraint and the skill
will keep failing even after patching.

## Output
A JSON array of 2-3 candidates:
```json
[
  {{
    "patches": [
      {{"section": "constraints", "action": "add", "content": "- MUST ..."}},
      {{"section": "examples", "action": "add", "content": "Query: ...\\nExpected: ..."}}
    ],
    "reasons": ["what this patch fixes"],
    "risk": "low|medium|high"
  }}
]
```

Output ONLY the JSON array. No explanation, no markdown fences.
"""

PATCHER_USER = """\
Skill: {skill_name}
Failure tag: {failure_tag}
Failure reason: {failure_reason}

CURRENT SECTIONS:

[constraints]
{constraints}

[tools]
{tools_section}

[output_format]
{output_format}

[examples]
{examples}

ACTUAL OUTPUT THAT FAILED:
{failed_output}

EXPECTED BEHAVIOR:
{expected_behavior}

TRACE CONTEXT:
Tool Calls (recent): {tool_calls}
Evidence Keys (recent): {evidence_keys}

REMINDER: If your patch adds a constraint about what must be in the output, \
you MUST also include an "examples" patch showing exactly what correct output \
looks like with that constraint satisfied. The example content should use the \
actual failed output above as a base and correct it to show the right behavior.

Generate 2-3 candidate patches as a JSON array.
"""


@dataclass
class SectionPatch:
    section: str
    action: str
    content: str


@dataclass
class PatchCandidate:
    candidate_id: str
    patched_skill_md: str
    patches: list[SectionPatch] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    risk: str = "low"

    @property
    def patched_prompt(self) -> str:
        """Compile the patched SKILL.md into a prompt for replay."""
        _, sections = parse_skill_md(self.patched_skill_md)
        return _compile_from_sections(sections)


def _compile_from_sections(s: SkillSections) -> str:
    parts: list[str] = []
    if s.title:
        parts.append(f"# {s.title}")
    if s.description_body:
        parts.append(s.description_body)
    if s.when_to_use:
        parts.append(f"## When to Use\n\n{s.when_to_use}")
    if s.when_not_to_use:
        parts.append(f"## When NOT to Use\n\n{s.when_not_to_use}")
    if s.constraints:
        parts.append(f"## Constraints\n\n{s.constraints}")
    if s.tools:
        parts.append(f"## Tools\n\n{s.tools}")
    if s.output_format:
        parts.append(f"## Output Format\n\n{s.output_format}")
    if s.examples:
        parts.append(f"## Examples\n\n{s.examples}")
    for heading, body in s.extra.items():
        parts.append(f"## {heading}\n\n{body}")
    return "\n\n".join(parts)


def _reconstruct_skill_md(
    fm: dict[str, Any], sections: SkillSections
) -> str:
    """Build a clean SKILL.md from frontmatter dict and sections."""
    fm_text = ""
    if fm:
        fm_text = "---\n" + yaml.dump(
            fm, default_flow_style=False, sort_keys=False
        ) + "---\n\n"
    return fm_text + _compile_from_sections(sections)


async def generate_patches(
    skill: Skill,
    failure_tags: list[str],
    traces: list[dict[str, Any]],
    provider: BaseLLM,
    guide: str | None = None,
) -> list[PatchCandidate]:
    """Generate section-level patch candidates for a skill."""
    failure_reason, failed_output, expected = _extract_failure_context(
        skill.name, failure_tags, traces
    )
    tool_calls, evidence_keys = _extract_trace_context(traces)

    s = skill.sections

    system_prompt = PATCHER_SYSTEM
    if guide:
        system_prompt = (
            f"## USER GUIDING PRINCIPLES (HIGHEST PRIORITY)\n"
            f"{guide}\n\n"
            f"You MUST follow the above principles when generating patches. "
            f"They override any conflicting default rules below.\n\n"
            f"{PATCHER_SYSTEM}"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": PATCHER_USER.format(
                skill_name=skill.name,
                failure_tag=", ".join(failure_tags),
                failure_reason=failure_reason,
                constraints=s.constraints or "(empty)",
                tools_section=s.tools or "(empty)",
                output_format=s.output_format or "(empty)",
                examples=s.examples or "(empty)",
                failed_output=failed_output,
                expected_behavior=expected,
                tool_calls=tool_calls,
                evidence_keys=evidence_keys,
            ),
        },
    ]

    response = await provider.complete(
        messages=messages, temperature=0.7, max_tokens=4096
    )
    candidates = _parse_candidates(response.content, skill)

    valid = []
    for c in candidates:
        if _validate_patch(skill.skill_md, c.patched_skill_md):
            valid.append(c)
        else:
            c.risk = "high"
            valid.append(c)

    return valid


def _extract_failure_context(
    skill_name: str,
    failure_tags: list[str],
    traces: list[dict[str, Any]],
) -> tuple[str, str, str]:
    """Pull concrete failure details from stored traces."""
    reasons: list[str] = []
    failed_output = "(no trace available)"
    expected = "The skill should follow all its MUST constraints."

    for trace in traces[:3]:
        eval_data = trace.get("eval", {})
        for se in eval_data.get("per_skill", []):
            if se.get("skill") != skill_name:
                continue
            for f in se.get("failures", []):
                reason = f.get("reason", "")
                if reason and reason not in reasons:
                    reasons.append(reason)

        steps = trace.get("steps", {})
        for step_data in steps.values():
            if step_data.get("skill") == skill_name:
                output = step_data.get("output", {})
                failed_output = json.dumps(output, indent=2)
                break
        if reasons:
            break

    if not reasons:
        for tag in failure_tags:
            if "no_tool_calls" in tag or "skipped" in tag:
                reasons.append(
                    "Skill had tools available but did not call them."
                )
                expected = (
                    "The skill should actively call its available tools "
                    "via function calling, not just describe plans."
                )
            elif "missing" in tag or "citation" in tag:
                reasons.append(
                    "Output did not cite evidence from gathered data."
                )
                expected = (
                    "The skill should cite evidence IDs "
                    "(e.g., [e1], [e2]) for all factual claims."
                )
            elif "format" in tag:
                reasons.append("Output format did not match the schema.")
                expected = (
                    "The skill should output valid JSON matching "
                    "the Output Format spec."
                )
            else:
                reasons.append(f"Failure: {tag}")

    if reasons and expected == "The skill should follow all its MUST constraints.":
        expected = "Fix the specific failure described above."

    return "; ".join(reasons) or "Constraint violation", failed_output, expected


def _extract_trace_context(traces: list[dict[str, Any]]) -> tuple[str, str]:
    """Summarize recent tool calls and evidence keys for patch context."""
    if not traces:
        return "(none)", "(none)"

    trace = traces[0]
    tool_calls = trace.get("tool_calls", [])
    if tool_calls:
        lines = []
        for tc in tool_calls[:8]:
            name = tc.get("tool", "?")
            ok = "OK" if tc.get("ok") else "FAILED"
            args = json.dumps(tc.get("args", {}))[:200]
            lines.append(f"- {name}({args}) -> {ok}")
        tool_calls_text = "\n".join(lines)
    else:
        tool_calls_text = "(none)"

    evidence = trace.get("evidence", {})
    if evidence:
        keys = list(evidence.keys())[:10]
        evidence_text = ", ".join(keys)
    else:
        evidence_text = "(none)"

    return tool_calls_text, evidence_text


def _parse_candidates(
    content: str, skill: Skill
) -> list[PatchCandidate]:
    """Parse LLM response into PatchCandidate objects."""
    content = content.strip()

    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    json_match = re.search(r"\[.*\]", content, re.DOTALL)
    if json_match:
        content = json_match.group()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        data = [data]

    candidates = []
    for item in data:
        if not isinstance(item, dict):
            continue

        raw_patches = item.get("patches", [])
        if not raw_patches:
            continue

        section_patches = []
        for p in raw_patches:
            if isinstance(p, dict) and p.get("section"):
                section_patches.append(SectionPatch(
                    section=p["section"],
                    action=p.get("action", "add"),
                    content=p.get("content", ""),
                ))

        if not section_patches:
            continue

        patched_md = _apply_patches(skill, raw_patches)
        if not patched_md:
            continue

        candidates.append(PatchCandidate(
            candidate_id=str(uuid.uuid4())[:8],
            patched_skill_md=patched_md,
            patches=section_patches,
            reasons=item.get("reasons", []),
            risk=item.get("risk", "low"),
        ))

    return candidates


_SECTION_ATTR_MAP: dict[str, str] = {
    "constraints": "constraints",
    "tools": "tools",
    "output_format": "output_format",
    "output format": "output_format",
    "examples": "examples",
    "when_to_use": "when_to_use",
    "when to use": "when_to_use",
    "when_not_to_use": "when_not_to_use",
    "when not to use": "when_not_to_use",
}


def _apply_patches(
    skill: Skill, patches: list[dict[str, Any]]
) -> str:
    """Apply section patches to the original SKILL.md and reconstruct."""
    if not patches:
        return ""

    fm, sections = parse_skill_md(skill.skill_md)

    for patch in patches:
        if not isinstance(patch, dict):
            continue
        section_key = patch.get("section", "").lower().strip()
        action = patch.get("action", "add")
        content = patch.get("content", "")
        attr = _SECTION_ATTR_MAP.get(section_key)
        if not attr or not content:
            continue
        current = getattr(sections, attr, "")
        if action == "replace":
            setattr(sections, attr, content)
        else:
            new_val = (
                f"{current}\n{content}".strip() if current else content
            )
            setattr(sections, attr, new_val)

    return _reconstruct_skill_md(fm, sections)


def _validate_patch(original: str, patched: str) -> bool:
    """Verify the patched SKILL.md is valid and not a regression."""
    if not patched or len(patched) < 20:
        return False
    if len(patched) < len(original) * 0.5:
        return False
    if len(patched) > len(original) * 5:
        return False

    try:
        fm, sections = parse_skill_md(patched)
    except Exception:
        return False

    if not sections.constraints and not sections.output_format:
        return False

    return True
