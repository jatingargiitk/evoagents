"""evoagents score / mas failures — scoring and failure inspection."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from evoagents.core.config import EvoAgentsConfig, find_config
from evoagents.core.store import TraceStore

app = typer.Typer(invoke_without_command=True)
console = Console()


@app.callback(invoke_without_command=True)
def score(
    target: str = typer.Argument("last", help="'last' or a run ID."),
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """Score (or re-score) a run using LLM evaluation."""
    import asyncio

    asyncio.run(_score_async(target, config))


async def _score_async(target: str, config: str) -> None:
    from evoagents.core.skill import SkillRegistry
    from evoagents.providers.registry import build_providers
    from evoagents.scoring.evaluator import evaluate_trace

    cfg = _load_config(config)
    store = TraceStore(cfg.store.path)

    if target == "last":
        record = store.get_last_run()
    else:
        record = store.get_run(target)

    if record is None:
        console.print("[red]No run found.[/red]")
        raise typer.Exit(1)

    registry = SkillRegistry(cfg.skills_dir)
    providers = build_providers(cfg.models)
    judge = providers.get("judge", providers["executor"])

    result = await evaluate_trace(
        question=record.question,
        trace=record.trace_json,
        skills=registry.all(),
        provider=judge,
    )

    score_style = (
        "green" if result.score >= 0.7
        else "yellow" if result.score >= 0.4
        else "red"
    )
    console.print(f"[bold]Run:[/bold] {record.run_id}")
    console.print(
        f"[bold]Score:[/bold] [{score_style}]{result.score:.2f}[/{score_style}]"
    )

    if result.tags:
        console.print(
            f"[bold]Failure Tags:[/bold] [red]{', '.join(result.tags)}[/red]"
        )
    else:
        console.print("[bold]Failure Tags:[/bold] [green]none[/green]")

    for se in result.per_skill:
        if se.failures:
            for fail in se.failures:
                console.print(
                    f"  [dim]{se.skill}:[/dim] {fail.get('reason', fail.get('tag', ''))}"
                )


def _failures(
    target: str = "last",
    since: str | None = None,
    config: str = "evoagents.yaml",
) -> None:
    """Show runs with failure tags."""
    cfg = _load_config(config)
    store = TraceStore(cfg.store.path)

    if since:
        hours = _parse_duration(since)
        runs = store.get_runs_since(hours)
    elif target == "last":
        r = store.get_last_run()
        runs = [r] if r else []
    else:
        r = store.get_run(target)
        runs = [r] if r else []

    failures_found = [r for r in runs if r and r.rule_tags]
    if not failures_found:
        console.print("[green]No failures found.[/green]")
        return

    table = Table(title="Failures", show_lines=True)
    table.add_column("Run ID", style="cyan")
    table.add_column("Time", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Tags", style="red")

    for r in failures_found:
        ts = datetime.fromtimestamp(r.ts).strftime("%Y-%m-%d %H:%M")
        table.add_row(r.run_id, ts, f"{r.rule_score:.2f}", ", ".join(r.rule_tags))

    console.print(table)


def _parse_duration(s: str) -> float:
    m = re.match(r"(\d+(?:\.\d+)?)\s*(h|d|m)", s)
    if not m:
        return 24.0
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "d":
        return val * 24
    if unit == "m":
        return val / 60
    return val


def _load_config(config: str) -> EvoAgentsConfig:
    try:
        config_path = find_config(Path.cwd())
    except FileNotFoundError:
        config_path = Path(config)
    cfg = EvoAgentsConfig.load(config_path)
    return cfg.resolve_paths(config_path.parent)
