"""evoagents create-skill — interactively create a new skill with LLM assistance."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()

SKILL_GEN_SYSTEM = """\
You are a skill architect for EvoAgents. Given a skill name and description, \
generate a complete SKILL.md file.

A SKILL.md has YAML frontmatter and markdown sections. Here is the exact format:

```
---
name: {skill_name}
description: >
  {description}
version: v1
tools: []
judge:
  rubric:
    constraints: 0.35
    tool_use: 0.05
    grounding: 0.20
    helpfulness: 0.40
  rules:
    confidence_min: 0.55
---

# {Skill Title}

{One-line description.}

## When to Use

USE this skill when:
- {condition 1}
- {condition 2}

## When NOT to Use

DON'T use this skill when:
- {condition}

## Constraints

- MUST {rule 1}
- MUST {rule 2}
- NEVER {prohibition}

## Output Format

Respond with ONLY a JSON object:
{json schema with field descriptions}

## Examples

Query: "{example query}"
Expected output:
{example JSON output}
```

Rules:
- The `tools` field should be `[]` unless the skill needs web search or HTTP.
  Use `["web_search", "http_get"]` if the skill needs to fetch live data.
- Constraints should be specific, actionable MUST/NEVER rules.
- Output Format must define a concrete JSON schema.
- Include at least 2 examples with realistic queries and expected output.
- The judge rubric weights must sum to approximately 1.0.
- Adjust rubric weights based on the skill's nature:
  - For research/data skills: higher grounding and tool_use
  - For analysis skills: higher constraints and helpfulness
  - For synthesis skills: higher helpfulness and grounding

Output ONLY the complete SKILL.md content. No explanation, no extra text.
"""


def create_skill(
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """Interactively create a new skill using LLM generation."""
    import asyncio

    asyncio.run(_create_skill_async(config))


async def _create_skill_async(config_path: str) -> None:
    from evoagents.core.config import EvoAgentsConfig, find_config
    from evoagents.providers.registry import build_providers

    name = typer.prompt("Skill name (lowercase, e.g. weather_checker)")
    name = name.strip().lower().replace(" ", "_").replace("-", "_")

    description = typer.prompt("Description (what this skill does)")

    try:
        cp = find_config(Path.cwd())
    except FileNotFoundError:
        cp = Path(config_path)

    cfg = EvoAgentsConfig.load(cp).resolve_paths(cp.parent)
    providers = build_providers(cfg.models)
    executor = providers["executor"]

    console.print("\n[dim]Generating SKILL.md...[/dim]")

    messages = [
        {"role": "system", "content": SKILL_GEN_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Skill name: {name}\n"
                f"Description: {description}\n\n"
                f"Generate the complete SKILL.md."
            ),
        },
    ]

    response = await executor.complete(
        messages=messages, temperature=0.7, max_tokens=4096
    )

    skill_md = _clean_output(response.content)

    console.print()
    console.print(Panel(
        Syntax(skill_md, "markdown", theme="monokai", line_numbers=True),
        title=f"Generated SKILL.md for [cyan]{name}[/cyan]",
        border_style="green",
    ))

    confirm = typer.confirm("\nCreate this skill?")
    if not confirm:
        console.print("[dim]Cancelled.[/dim]")
        return

    skills_dir = Path(cfg.skills_dir)
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(skill_md)

    v1_dir = skill_dir / "versions" / "v1"
    v1_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(skill_file, v1_dir / "SKILL.md")

    console.print(
        f"\n[bold green]Created[/bold green] skills/{name}/SKILL.md (v1)"
    )

    add_to_pipeline = typer.confirm("Add to pipeline in evoagents.yaml?")
    if add_to_pipeline:
        _add_to_pipeline(cp, name)
        console.print(
            f"[bold green]Added[/bold green] [cyan]{name}[/cyan] to pipeline"
        )

    console.print(
        f'\n[dim]Next: evoagents run "your query here"[/dim]'
    )


def _clean_output(content: str) -> str:
    """Strip markdown fences if the LLM wrapped the output."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        content = "\n".join(lines).strip()
    return content


def _add_to_pipeline(config_path: Path, skill_name: str) -> None:
    """Append a new pipeline step to evoagents.yaml."""
    import yaml

    raw = config_path.read_text()
    data = yaml.safe_load(raw) or {}

    pipeline = data.get("pipeline", [])
    existing_names = {step.get("skill") for step in pipeline}
    if skill_name in existing_names:
        return

    pipeline.append({"name": skill_name, "skill": skill_name})
    data["pipeline"] = pipeline

    config_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
