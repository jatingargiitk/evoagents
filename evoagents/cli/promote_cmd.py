"""evoagents promote / rollback / versions / diff — skill version management."""

from __future__ import annotations

import difflib
from pathlib import Path

import typer
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from evoagents.core.config import EvoAgentsConfig, find_config
from evoagents.core.skill import SkillRegistry
from evoagents.core.store import TraceStore

app = typer.Typer(invoke_without_command=True)
console = Console()


@app.callback(invoke_without_command=True)
def promote(
    skill: str = typer.Option(..., "--skill", help="Skill name."),
    candidate: str = typer.Option("best", help="Candidate ID or 'best'."),
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """Manually promote a skill version."""
    console.print(
        "[yellow]Manual promotion is typically done via 'evoagents autofix'. "
        "Use 'evoagents rollback --skill <name>' to revert.[/yellow]"
    )


def _rollback(skill: str, config: str = "evoagents.yaml") -> None:
    cfg = _load_config(config)
    store = TraceStore(cfg.store.path)
    registry = SkillRegistry(cfg.skills_dir)

    sk = registry.get(skill)
    prev = sk.previous_version()
    if prev is None:
        console.print(f"[red]No previous version for {skill} (current: {sk.active_version}).[/red]")
        return

    old_version = sk.active_version
    sk.set_active_version(prev)
    store.log_event("rollback", skill, {"from": old_version, "to": prev})

    console.print(
        f"[bold green]✓[/bold green] Rolled back [cyan]{skill}[/cyan] "
        f"from {old_version} → [yellow]{prev}[/yellow]"
    )


def _versions(skill: str, config: str = "evoagents.yaml") -> None:
    cfg = _load_config(config)
    registry = SkillRegistry(cfg.skills_dir)

    sk = registry.get(skill)
    versions = sk.list_versions()

    if not versions:
        console.print(f"[dim]No versions found for {skill}.[/dim]")
        return

    table = Table(title=f"Versions: {skill}")
    table.add_column("Version")
    table.add_column("Status")

    for v in versions:
        if v == sk.active_version:
            table.add_row(v, "[bold green]active[/bold green]")
        else:
            table.add_row(v, "[dim]inactive[/dim]")

    console.print(table)


def _diff(skill: str, v1: str, v2: str, config: str = "evoagents.yaml") -> None:
    cfg = _load_config(config)
    registry = SkillRegistry(cfg.skills_dir)

    sk = registry.get(skill)
    try:
        md_a = sk.get_version_skill_md(v1)
        md_b = sk.get_version_skill_md(v2)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        return

    diff_lines = list(difflib.unified_diff(
        md_a.splitlines(keepends=True),
        md_b.splitlines(keepends=True),
        fromfile=f"{skill}/{v1}/SKILL.md",
        tofile=f"{skill}/{v2}/SKILL.md",
    ))

    if not diff_lines:
        console.print("[dim]No differences.[/dim]")
        return

    diff_text = "".join(diff_lines)
    console.print(Syntax(diff_text, "diff", theme="monokai"))


def _load_config(config: str) -> EvoAgentsConfig:
    try:
        config_path = find_config(Path.cwd())
    except FileNotFoundError:
        config_path = Path(config)
    cfg = EvoAgentsConfig.load(config_path)
    return cfg.resolve_paths(config_path.parent)
