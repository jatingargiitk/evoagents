"""Configuration system — Pydantic models for evoagents.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class PipelineStep(BaseModel):
    name: str
    skill: str


class ModelConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"


class ModelsConfig(BaseModel):
    executor: ModelConfig = Field(default_factory=ModelConfig)
    judge: ModelConfig | None = None

    @model_validator(mode="after")
    def _default_judge_to_executor(self) -> "ModelsConfig":
        if self.judge is None:
            self.judge = self.executor.model_copy()
        return self


class SelfImproveConfig(BaseModel):
    enabled: bool = True
    replay_window: int = 15
    promote_threshold: float = 0.70


class RuntimeConfig(BaseModel):
    tools: dict[str, str] = Field(default_factory=dict)
    max_steps: int = 50


class StoreConfig(BaseModel):
    type: str = "sqlite"
    path: str = "./.selfheal/runs.sqlite"


class EvoAgentsConfig(BaseModel):
    """Root configuration loaded from evoagents.yaml."""

    pipeline: list[PipelineStep] = Field(default_factory=list)
    skills_dir: str = "./skills"
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    self_improve: SelfImproveConfig = Field(default_factory=SelfImproveConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    store: StoreConfig = Field(default_factory=StoreConfig)

    @classmethod
    def load(cls, path: str | Path) -> "EvoAgentsConfig":
        """Load config from a YAML file, with env-var interpolation."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        raw = path.read_text()
        raw = _interpolate_env(raw)
        data = yaml.safe_load(raw) or {}
        return cls.model_validate(data)

    def resolve_paths(self, base: Path) -> "EvoAgentsConfig":
        """Resolve relative paths against a base directory."""
        data = self.model_dump()
        data["skills_dir"] = str((base / self.skills_dir).resolve())
        data["store"]["path"] = str((base / self.store.path).resolve())
        return EvoAgentsConfig.model_validate(data)


def _interpolate_env(text: str) -> str:
    """Replace ${VAR} and $VAR patterns with environment variable values."""
    import re

    def _replace(match: Any) -> str:
        var = match.group(1) or match.group(2)
        return os.environ.get(var, match.group(0))

    return re.sub(r"\$\{(\w+)\}|\$(\w+)", _replace, text)


def find_config(start: Path | None = None) -> Path:
    """Walk up from *start* looking for evoagents.yaml."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / "evoagents.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No evoagents.yaml found in current directory or parents")
