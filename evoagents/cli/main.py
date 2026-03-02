"""CLI entrypoint — Typer app with all subcommands."""

from __future__ import annotations

import typer

from evoagents.cli.autofix_cmd import autofix
from evoagents.cli.create_skill_cmd import create_skill
from evoagents.cli.init_cmd import app as init_app
from evoagents.cli.promote_cmd import app as promote_app
from evoagents.cli.run_cmd import app as run_app
from evoagents.cli.score_cmd import app as score_app
from evoagents.cli.stats_cmd import app as stats_app
from evoagents.cli.trace_cmd import app as trace_app

app = typer.Typer(
    name="evoagents",
    help="Agents that evolve their own skills. Self-healing multi-agent systems.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

app.add_typer(init_app, name="init", help="Initialize a new EvoAgents project.")
app.add_typer(run_app, name="run", help="Run the pipeline on a query.")
app.add_typer(trace_app, name="trace", help="Inspect run traces.")
app.add_typer(score_app, name="score", help="Score and inspect failures.")
app.command("autofix")(autofix)
app.command("create-skill")(create_skill)
app.add_typer(promote_app, name="promote", help="Promote, rollback, version skills.")
app.add_typer(stats_app, name="stats", help="View run statistics.")


@app.command("list-runs")
def list_runs(
    limit: int = typer.Option(20, help="Number of runs to show."),
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """List recent pipeline runs."""
    from evoagents.cli.trace_cmd import _list_runs

    _list_runs(limit=limit, config=config)


@app.command("failures")
def failures(
    target: str = typer.Argument("last", help="'last' or a run ID."),
    since: str | None = typer.Option(None, help="Show failures since Nh (e.g. '24h')."),
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """Show failure tags for runs."""
    from evoagents.cli.score_cmd import _failures

    _failures(target=target, since=since, config=config)


@app.command("rollback")
def rollback(
    skill: str = typer.Option(..., "--skill", help="Skill name to rollback."),
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """Rollback a skill to its previous version."""
    from evoagents.cli.promote_cmd import _rollback

    _rollback(skill=skill, config=config)


@app.command("versions")
def versions(
    skill: str = typer.Option(..., "--skill", help="Skill name."),
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """List versions of a skill."""
    from evoagents.cli.promote_cmd import _versions

    _versions(skill=skill, config=config)


@app.command("diff")
def diff_cmd(
    skill: str = typer.Option(..., "--skill", help="Skill name."),
    v1: str = typer.Argument(..., help="First version (e.g. v1)."),
    v2: str = typer.Argument(..., help="Second version (e.g. v2)."),
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """Diff two versions of a skill prompt."""
    from evoagents.cli.promote_cmd import _diff

    _diff(skill=skill, v1=v1, v2=v2, config=config)
