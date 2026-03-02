"""evoagents autofix — generate patches, replay, and promote."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def autofix(
    target: str = typer.Argument("last", help="'last' or a run ID."),
    skill: str | None = typer.Option(
        None, "--skill", help="Target a specific skill."
    ),
    last: int = typer.Option(
        15, "--last", help="Number of recent traces to consider."
    ),
    auto: bool = typer.Option(
        False, "--auto", help="Auto-promote without confirmation."
    ),
    guide: str | None = typer.Option(
        None, "--guide", help="Guiding principles for the patcher (highest priority)."
    ),
    config: str = typer.Option("evoagents.yaml", help="Path to config file."),
) -> None:
    """Auto-patch failing skills using LLM evaluation and replay gating."""
    import asyncio

    asyncio.run(_autofix_async(target, skill, last, auto, config, guide=guide))


async def _autofix_async(
    target: str,
    skill_name: str | None,
    last: int,
    auto: bool,
    config_path: str,
    *,
    guide: str | None = None,
) -> None:
    from evoagents.core.config import EvoAgentsConfig, find_config
    from evoagents.core.skill import SkillRegistry
    from evoagents.core.store import TraceStore
    from evoagents.improve.patcher import generate_patches
    from evoagents.improve.promotion import promote_skill
    from evoagents.improve.replay import replay_and_evaluate
    from evoagents.providers.registry import build_providers

    try:
        cp = find_config(Path.cwd())
    except FileNotFoundError:
        cp = Path(config_path)

    cfg = EvoAgentsConfig.load(cp).resolve_paths(cp.parent)
    store = TraceStore(cfg.store.path)
    registry = SkillRegistry(cfg.skills_dir)
    providers = build_providers(cfg.models)

    if target == "last":
        record = store.get_last_run()
    else:
        record = store.get_run(target)

    if record is None:
        console.print("[red]No run found.[/red]")
        raise typer.Exit(1)

    _show_eval_summary(record)

    if not record.rule_tags:
        console.print(
            "[green]No failures detected. Nothing to fix.[/green]"
        )
        return

    failing_skills = _identify_failing_skills(
        record, registry, skill_name
    )
    if not failing_skills:
        console.print(
            "[yellow]No matching skills for the failure tags.[/yellow]"
        )
        return

    for sk_name, skill_info in failing_skills.items():
        sk = registry.get(sk_name)
        tags = skill_info["tags"]
        reasons = skill_info["reasons"]

        console.print(Panel(
            f"[bold]Skill:[/bold] {sk_name} ({sk.active_version})\n"
            f"[bold]Score:[/bold] [red]{skill_info['score']:.2f}[/red]\n"
            f"[bold]Failures:[/bold] [red]{'; '.join(reasons)}[/red]",
            title="Autofix Target",
        ))

        console.print("[dim]Generating patches...[/dim]")
        recent_traces = store.query_by_tags(tags, limit=last)
        candidates = await generate_patches(
            skill=sk,
            failure_tags=tags,
            traces=[r.trace_json for r in recent_traces[:5]],
            provider=providers["judge"],
            guide=guide,
        )

        if not candidates:
            console.print(
                f"[yellow]No patches generated for {sk_name}.[/yellow]"
            )
            continue

        _show_patch_summary(candidates)

        console.print("[dim]Running replay gate...[/dim]")
        result = await replay_and_evaluate(
            skill=sk,
            candidates=candidates,
            recent_runs=recent_traces,
            cfg=cfg,
            providers=providers,
        )

        if result.winner is None:
            console.print(
                f"[yellow]No candidate passed the replay gate "
                f"for {sk_name}.[/yellow]"
            )
            for cr in result.candidate_results:
                console.print(
                    f"  Candidate {cr.candidate.candidate_id}: "
                    f"win_rate={cr.win_rate:.0%} "
                    f"avg_delta={cr.avg_delta:+.2f}"
                )
            continue

        console.print(Panel(
            f"[bold]Winner:[/bold] {result.winner.candidate_id}\n"
            f"[bold]Win rate:[/bold] [green]{result.win_rate:.0%}[/green]\n"
            f"[bold]Score delta:[/bold] [green]{result.avg_delta:+.2f}[/green]\n"
            f"[bold]Fixed:[/bold] {', '.join(result.fixed_tags) or 'score improvement'}\n"
            f"[bold]Patches:[/bold] {_format_patches_short(result.winner.patches)}",
            title="Replay Gate Passed",
            border_style="green",
        ))

        if not auto:
            confirm = typer.confirm(
                f"Promote {sk_name} to new version?"
            )
            if not confirm:
                console.print("[dim]Skipped.[/dim]")
                continue

        old_version = sk.active_version
        new_version = promote_skill(
            sk, result.winner.patched_skill_md, store
        )
        console.print(
            f"[bold green]Promoted[/bold green] [cyan]{sk_name}[/cyan] "
            f"{old_version} -> [green]{new_version}[/green]"
        )

    console.print(
        "\n[dim]Run 'evoagents run' to test the improvements.[/dim]"
    )


def _show_eval_summary(record) -> None:  # noqa: ANN001
    """Show per-skill evaluation from the trace."""
    eval_data = record.trace_json.get("eval", {})
    per_skill = eval_data.get("per_skill", [])

    if not per_skill:
        return

    table = Table(title="Evaluation Summary", show_lines=True)
    table.add_column("Skill", style="cyan")
    table.add_column("Score", justify="center")
    table.add_column("Failures")

    for se in per_skill:
        score = se.get("score", 0)
        style = (
            "green" if score >= 0.7
            else "yellow" if score >= 0.4
            else "red"
        )
        failures_text = ""
        for f in se.get("failures", []):
            failures_text += f"- {f.get('reason', f.get('tag', ''))}\n"
        if not failures_text:
            failures_text = "[green]none[/green]"

        table.add_row(
            se.get("skill", "?"),
            f"[{style}]{score:.2f}[/{style}]",
            failures_text.strip(),
        )

    console.print(table)
    console.print()


def _show_patch_summary(candidates) -> None:  # noqa: ANN001
    """Show what each candidate patches."""
    console.print(f"  [cyan]{len(candidates)}[/cyan] candidates:")
    for c in candidates:
        sections = [p.section for p in c.patches]
        console.print(
            f"    [{c.candidate_id}] "
            f"patches: {', '.join(sections)} | "
            f"risk: {c.risk} | "
            f"reasons: {', '.join(c.reasons)}"
        )


def _format_patches_short(patches) -> str:  # noqa: ANN001
    """One-line summary of patches."""
    parts = []
    for p in patches:
        preview = p.content[:60].replace("\n", " ")
        parts.append(f"{p.section}({p.action}): {preview}")
    return "; ".join(parts)


def _identify_failing_skills(
    record, registry, skill_name: str | None  # noqa: ANN001
) -> dict[str, dict[str, Any]]:
    """Map failure tags to skills using per-skill eval data."""

    eval_data = record.trace_json.get("eval", {})
    per_skill = eval_data.get("per_skill", [])
    all_skills = registry.list_skills()

    if per_skill:
        result: dict[str, dict[str, Any]] = {}
        for se in per_skill:
            sk = se.get("skill", "")
            if sk not in all_skills:
                continue
            if skill_name and sk != skill_name:
                continue
            tags = se.get("tags", [])
            failures = se.get("failures", [])
            if not tags and not failures:
                continue
            reasons = [
                f.get("reason", f.get("tag", ""))
                for f in failures
            ]
            result[sk] = {
                "tags": tags,
                "reasons": reasons or [str(t) for t in tags],
                "score": se.get("score", 0),
            }
        return result

    skill_tags: dict[str, dict[str, Any]] = {}
    for tag in record.rule_tags:
        prefix = tag.split(".")[0] if "." in tag else None

        if skill_name:
            skill_tags.setdefault(skill_name, {
                "tags": [], "reasons": [], "score": record.rule_score,
            })["tags"].append(tag)
            continue

        matched = False
        if prefix:
            for sk in all_skills:
                if sk == prefix or sk.startswith(prefix) or prefix.startswith(sk):
                    skill_tags.setdefault(sk, {
                        "tags": [], "reasons": [], "score": record.rule_score,
                    })["tags"].append(tag)
                    matched = True
                    break

        if not matched and all_skills:
            skill_tags.setdefault(all_skills[0], {
                "tags": [], "reasons": [], "score": record.rule_score,
            })["tags"].append(tag)

    for info in skill_tags.values():
        if not info["reasons"]:
            info["reasons"] = info["tags"]

    return skill_tags
