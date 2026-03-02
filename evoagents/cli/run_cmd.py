"""evoagents run — execute the pipeline on a query."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(invoke_without_command=True)
console = Console()


@app.callback(invoke_without_command=True)
def run(
    question: str = typer.Argument(
        ..., help="The query to run through the pipeline."
    ),
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """Run the full pipeline on a question."""
    import asyncio

    asyncio.run(_run_async(question, config))


async def _run_async(
    question: str, config_path: str
) -> None:
    from evoagents.core.config import EvoAgentsConfig, find_config
    from evoagents.core.pipeline import PipelineRunner
    from evoagents.core.store import TraceStore

    try:
        cp = find_config(Path.cwd())
    except FileNotFoundError:
        cp = Path(config_path)

    cfg = EvoAgentsConfig.load(cp).resolve_paths(cp.parent)

    store = TraceStore(cfg.store.path)
    prev_record = store.get_last_run()

    runner = PipelineRunner(cfg)
    record = await runner.run(question)

    console.print()
    console.print(f"[bold]Run:[/bold] {record.run_id}")

    _show_score(record, prev_record)
    _show_per_skill(record)
    _show_tags(record, prev_record)
    _show_answer(record)

    console.print(
        f"\n[dim]Trace stored. "
        f"Run 'evoagents trace {record.run_id}' for details.[/dim]"
    )

    if record.rule_tags:
        console.print(
            "[dim]Run 'evoagents autofix' to fix the issues above.[/dim]"
        )


def _show_score(record, prev_record) -> None:  # noqa: ANN001
    """Show score with delta from previous run."""
    score = record.rule_score
    style = (
        "green" if score >= 0.7
        else "yellow" if score >= 0.4
        else "red"
    )

    score_text = f"[{style}]{score:.2f}[/{style}]"

    if prev_record is not None:
        prev_score = prev_record.rule_score
        delta = score - prev_score
        if delta > 0:
            score_text += f" [green](+{delta:.2f} from prev)[/green]"
        elif delta < 0:
            score_text += f" [red]({delta:.2f} from prev)[/red]"
        else:
            score_text += " [dim](unchanged)[/dim]"

    console.print(f"[bold]Score:[/bold] {score_text}")


def _show_per_skill(record) -> None:  # noqa: ANN001
    """Show per-skill scores in a compact table."""
    eval_data = record.trace_json.get("eval", {})
    per_skill = eval_data.get("per_skill", [])

    if not per_skill:
        return

    table = Table(show_header=True, show_lines=False, pad_edge=False)
    table.add_column("Skill", style="cyan", min_width=12)
    table.add_column("Score", justify="center", min_width=6)
    table.add_column("Issues", min_width=20)

    for se in per_skill:
        score = se.get("score", 0)
        style = (
            "green" if score >= 0.7
            else "yellow" if score >= 0.4
            else "red"
        )
        issues = [
            f.get("reason", "") for f in se.get("failures", [])
        ]
        issues_text = (
            "; ".join(issues)[:80] if issues
            else "[green]ok[/green]"
        )
        table.add_row(
            se.get("skill", "?"),
            f"[{style}]{score:.2f}[/{style}]",
            issues_text,
        )

    console.print(table)


def _show_tags(record, prev_record) -> None:  # noqa: ANN001
    """Show tags with comparison to previous run."""
    current_tags = set(record.rule_tags)
    prev_tags = set(prev_record.rule_tags) if prev_record else set()

    fixed = prev_tags - current_tags
    new_issues = current_tags - prev_tags
    remaining = current_tags & prev_tags

    if fixed:
        console.print(
            f"[bold green]Fixed:[/bold green] "
            f"{', '.join(sorted(fixed))}"
        )

    if remaining:
        console.print(
            f"[bold yellow]Remaining:[/bold yellow] "
            f"{', '.join(sorted(remaining))}"
        )

    if new_issues:
        console.print(
            f"[bold red]New issues:[/bold red] "
            f"{', '.join(sorted(new_issues))}"
        )

    if not current_tags:
        console.print("[bold green]No issues detected.[/bold green]")


def _show_answer(record) -> None:  # noqa: ANN001
    """Show the final pipeline output."""
    steps = record.trace_json.get("steps", {})
    pipeline_order = record.trace_json.get("pipeline", [])
    if not pipeline_order:
        return

    last_step = pipeline_order[-1]
    output = steps.get(last_step, {}).get("output", {})
    answer = output.get("answer", output.get("text", str(output)))
    console.print(f"\n[bold]Answer:[/bold]\n{answer}")
