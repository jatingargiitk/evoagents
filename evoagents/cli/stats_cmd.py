"""evoagents stats — view run statistics."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from evoagents.core.config import EvoAgentsConfig, find_config
from evoagents.core.store import TraceStore

app = typer.Typer(invoke_without_command=True)
console = Console()


@app.callback(invoke_without_command=True)
def stats(
    skill: str | None = typer.Option(None, "--skill", help="Filter by skill."),
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """View aggregate run statistics."""
    cfg = _load_config(config)
    store = TraceStore(cfg.store.path)

    total = store.count_runs()
    if total == 0:
        console.print("[dim]No runs recorded yet.[/dim]")
        return

    avg = store.avg_score(skill)
    runs = store.list_runs(100)

    failure_count = sum(1 for r in runs if r.rule_tags)
    tag_counts: dict[str, int] = {}
    for r in runs:
        for tag in r.rule_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    title = f"Stats: {skill}" if skill else "Stats: All Skills"
    console.print(Panel(
        f"[bold]Total runs:[/bold] {total}\n"
        f"[bold]Avg score:[/bold] {avg:.2f}\n"
        f"[bold]Failure rate:[/bold] {failure_count}/{len(runs)} "
        f"({failure_count / len(runs):.0%})" if runs else "",
        title=title,
    ))

    if tag_counts:
        table = Table(title="Top Failure Tags")
        table.add_column("Tag", style="red")
        table.add_column("Count", justify="right")
        for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])[:10]:
            table.add_row(tag, str(count))
        console.print(table)

    events = store.get_events(limit=10)
    if events:
        ev_table = Table(title="Recent Events")
        ev_table.add_column("Time", style="dim")
        ev_table.add_column("Type")
        ev_table.add_column("Skill")
        for ev in events:
            ts = datetime.fromtimestamp(ev["ts"]).strftime("%m-%d %H:%M")
            ev_table.add_row(ts, ev["event_type"], ev.get("skill_name") or "—")
        console.print(ev_table)


def _load_config(config: str) -> EvoAgentsConfig:
    try:
        config_path = find_config(Path.cwd())
    except FileNotFoundError:
        config_path = Path(config)
    cfg = EvoAgentsConfig.load(config_path)
    return cfg.resolve_paths(config_path.parent)
