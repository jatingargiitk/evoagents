"""evoagents trace — inspect run traces."""

from __future__ import annotations

import json
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
def trace(
    target: str = typer.Argument("last", help="'last' or a run ID."),
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """Inspect a pipeline run trace."""
    cfg = _load_config(config)
    store = TraceStore(cfg.store.path)

    if target == "last":
        record = store.get_last_run()
    else:
        record = store.get_run(target)

    if record is None:
        console.print("[red]No run found.[/red]")
        raise typer.Exit(1)

    _print_trace(record)


def _list_runs(limit: int = 20, config: str = "evoagents.yaml") -> None:
    cfg = _load_config(config)
    store = TraceStore(cfg.store.path)
    runs = store.list_runs(limit)

    if not runs:
        console.print("[dim]No runs found.[/dim]")
        return

    table = Table(title="Recent Runs", show_lines=True)
    table.add_column("Run ID", style="cyan")
    table.add_column("Time", style="dim")
    table.add_column("Question", max_width=50)
    table.add_column("Score", justify="right")
    table.add_column("Tags")

    for r in runs:
        ts = datetime.fromtimestamp(r.ts).strftime("%Y-%m-%d %H:%M")
        score_style = "green" if r.rule_score >= 0.7 else "yellow" if r.rule_score >= 0.4 else "red"
        table.add_row(
            r.run_id,
            ts,
            r.question[:50],
            f"[{score_style}]{r.rule_score:.2f}[/{score_style}]",
            ", ".join(r.rule_tags) if r.rule_tags else "[dim]none[/dim]",
        )
    console.print(table)


def _print_trace(record) -> None:  # noqa: ANN001
    from evoagents.core.store import RunRecord

    r: RunRecord = record
    ts = datetime.fromtimestamp(r.ts).strftime("%Y-%m-%d %H:%M:%S")
    score_style = "green" if r.rule_score >= 0.7 else "yellow" if r.rule_score >= 0.4 else "red"

    console.print(Panel(
        f"[bold]Run:[/bold] {r.run_id}\n"
        f"[bold]Time:[/bold] {ts}\n"
        f"[bold]Question:[/bold] {r.question}\n"
        f"[bold]Score:[/bold] [{score_style}]{r.rule_score:.2f}[/{score_style}]\n"
        f"[bold]Tags:[/bold] {', '.join(r.rule_tags) if r.rule_tags else 'none'}",
        title="Trace Summary",
    ))

    trace_data = r.trace_json
    steps = trace_data.get("steps", {})
    for step_name, step_data in steps.items():
        version = step_data.get("version", "?")
        output = step_data.get("output", {})
        output_preview = json.dumps(output, indent=2)[:500]
        console.print(Panel(
            f"[bold]Skill:[/bold] {step_data.get('skill', step_name)} [dim]({version})[/dim]\n"
            f"[bold]Output:[/bold]\n{output_preview}",
            title=f"Step: {step_name}",
            border_style="blue",
        ))

    tool_calls = trace_data.get("tool_calls", [])
    if tool_calls:
        tc_table = Table(title="Tool Calls")
        tc_table.add_column("Tool")
        tc_table.add_column("OK")
        tc_table.add_column("Latency")
        for tc in tool_calls:
            ok_str = "[green]✓[/green]" if tc.get("ok") else "[red]✗[/red]"
            tc_table.add_row(tc.get("tool", "?"), ok_str, f"{tc.get('latency_ms', '?')}ms")
        console.print(tc_table)


def _load_config(config: str) -> EvoAgentsConfig:
    try:
        config_path = find_config(Path.cwd())
    except FileNotFoundError:
        config_path = Path(config)
    cfg = EvoAgentsConfig.load(config_path)
    return cfg.resolve_paths(config_path.parent)
