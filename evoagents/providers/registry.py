"""Provider factory — build LLM providers from config."""

from __future__ import annotations

from evoagents.core.config import ModelsConfig
from evoagents.providers.base import BaseLLM


def build_provider(provider: str, model: str) -> BaseLLM:
    """Instantiate a single LLM provider by name."""
    provider = provider.lower()
    if provider == "openai":
        from evoagents.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model)
    elif provider == "anthropic":
        from evoagents.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model)
    else:
        raise ValueError(f"Unknown provider: {provider}. Supported: openai, anthropic")


def build_providers(models_cfg: ModelsConfig) -> dict[str, BaseLLM]:
    """Build executor and judge providers from config.

    Returns dict with keys "executor" and "judge".
    If judge config matches executor, reuses the same instance.
    """
    executor = build_provider(
        models_cfg.executor.provider,
        models_cfg.executor.model,
    )

    judge_cfg = models_cfg.judge or models_cfg.executor
    if (
        judge_cfg.provider == models_cfg.executor.provider
        and judge_cfg.model == models_cfg.executor.model
    ):
        judge = executor
    else:
        judge = build_provider(judge_cfg.provider, judge_cfg.model)

    return {"executor": executor, "judge": judge}
