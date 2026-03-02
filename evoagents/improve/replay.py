"""Replay gate — evaluate patch candidates via per-skill score comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evoagents.core.config import EvoAgentsConfig
from evoagents.core.skill import Skill
from evoagents.core.store import RunRecord
from evoagents.improve.patcher import PatchCandidate
from evoagents.providers.base import BaseLLM
from evoagents.scoring.evaluator import evaluate_single_skill


@dataclass
class CandidateResult:
    candidate: PatchCandidate
    wins: int = 0
    losses: int = 0
    ties: int = 0
    score_deltas: list[float] = field(default_factory=list)
    fixed_tags: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_rate(self) -> float:
        decided = self.wins + self.losses
        return self.wins / decided if decided > 0 else 0.0

    @property
    def avg_delta(self) -> float:
        return (
            sum(self.score_deltas) / len(self.score_deltas)
            if self.score_deltas else 0.0
        )


@dataclass
class ReplayResult:
    winner: PatchCandidate | None = None
    win_rate: float = 0.0
    avg_delta: float = 0.0
    fixed_tags: list[str] = field(default_factory=list)
    candidate_results: list[CandidateResult] = field(default_factory=list)


async def replay_and_evaluate(
    skill: Skill,
    candidates: list[PatchCandidate],
    recent_runs: list[RunRecord],
    cfg: EvoAgentsConfig,
    providers: dict[str, BaseLLM],
) -> ReplayResult:
    """Run candidates through the replay gate using per-skill evaluation.

    Compares the evaluator score for the patched skill output against the
    baseline score. No pairwise judge — direct score comparison is cleaner.
    """
    from evoagents.core.pipeline import PipelineRunner

    if not candidates or not recent_runs:
        return ReplayResult()

    runner = PipelineRunner(cfg)
    judge_provider = providers["judge"]
    si = cfg.self_improve

    step_name = _find_skill_step(skill.name, cfg)
    if step_name is None:
        return ReplayResult()

    replay_traces = recent_runs[:si.replay_window]

    threshold = si.promote_threshold
    if len(replay_traces) == 1:
        threshold = 0.50

    candidate_results: list[CandidateResult] = []

    for candidate in candidates:
        cr = CandidateResult(candidate=candidate)

        for run_record in replay_traces:
            trace = run_record.trace_json
            question = trace.get("question", run_record.question)

            baseline_step = _extract_step_data(trace, step_name)
            if baseline_step is None:
                continue

            baseline_output = baseline_step.get("output", {})
            baseline_tool_calls = _get_skill_tool_calls(
                trace, skill
            )

            baseline_eval = await evaluate_single_skill(
                question=question,
                skill_name=skill.name,
                skill=skill,
                step_output=baseline_output,
                tool_calls=baseline_tool_calls,
                upstream_outputs=_get_upstream_outputs(
                    trace, step_name
                ),
                provider=judge_provider,
            )

            try:
                new_trace = await runner.run_from_step(
                    question=question,
                    trace=trace,
                    start_step=step_name,
                    patched_prompt=candidate.patched_prompt,
                )
            except Exception:
                cr.ties += 1
                continue

            new_step = _extract_step_data(new_trace, step_name)
            if new_step is None:
                cr.ties += 1
                continue

            new_output = new_step.get("output", {})
            new_tool_calls = _get_skill_tool_calls(new_trace, skill)

            new_eval = await evaluate_single_skill(
                question=question,
                skill_name=skill.name,
                skill=skill,
                step_output=new_output,
                tool_calls=new_tool_calls,
                upstream_outputs=_get_upstream_outputs(
                    new_trace, step_name
                ),
                provider=judge_provider,
            )

            delta = new_eval.score - baseline_eval.score
            cr.score_deltas.append(delta)

            fixed = set(baseline_eval.tags) - set(new_eval.tags)
            if fixed:
                cr.fixed_tags.extend(fixed)

            if delta > 0.05:
                cr.wins += 1
            elif delta < -0.05:
                cr.losses += 1
            else:
                if fixed and not (set(new_eval.tags) - set(baseline_eval.tags)):
                    cr.wins += 1
                else:
                    cr.ties += 1

        candidate_results.append(cr)

    best = _select_winner(candidate_results, threshold)

    return ReplayResult(
        winner=best.candidate if best else None,
        win_rate=best.win_rate if best else 0.0,
        avg_delta=best.avg_delta if best else 0.0,
        fixed_tags=best.fixed_tags if best else [],
        candidate_results=candidate_results,
    )


def _find_skill_step(skill_name: str, cfg: EvoAgentsConfig) -> str | None:
    for step in cfg.pipeline:
        if step.skill == skill_name:
            return step.name
    return None


def _extract_step_data(
    trace: dict[str, Any], step_name: str
) -> dict | None:
    return trace.get("steps", {}).get(step_name)


def _get_skill_tool_calls(
    trace: dict[str, Any], skill: Any
) -> list[dict[str, Any]]:
    """Get tool calls that belong to a skill."""
    all_calls = trace.get("tool_calls", [])
    allowed = skill.tools.tools if skill.tools else []
    if not allowed:
        return []
    result = []
    for tc in all_calls:
        tool_name = tc.get("tool", "")
        api_name = tool_name.replace(".", "_")
        if tool_name in allowed or api_name in allowed:
            result.append(tc)
    return result


def _get_upstream_outputs(
    trace: dict[str, Any], target_step: str
) -> dict[str, Any]:
    """Get outputs from steps before the target step."""
    steps = trace.get("steps", {})
    pipeline = trace.get("pipeline", list(steps.keys()))
    upstream: dict[str, Any] = {}
    for step_name in pipeline:
        if step_name == target_step:
            break
        step = steps.get(step_name)
        if step:
            upstream[step_name] = step.get("output", {})
    return upstream


def _select_winner(
    results: list[CandidateResult],
    threshold: float,
) -> CandidateResult | None:
    """Select the best candidate that passes the threshold."""
    eligible = [cr for cr in results if cr.win_rate >= threshold]

    if not eligible:
        eligible = [
            cr for cr in results
            if cr.wins > 0 and cr.losses == 0
        ]

    if not eligible:
        return None

    eligible.sort(key=lambda cr: (cr.win_rate, cr.avg_delta), reverse=True)
    return eligible[0]
