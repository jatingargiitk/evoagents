"""Skill loader and version manager — OpenClaw-style SKILL.md format."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SKILL_FILENAME = "SKILL.md"


@dataclass
class JudgeRubric:
    weights: dict[str, float] = field(default_factory=lambda: {
        "constraints": 0.30,
        "tool_use": 0.30,
        "grounding": 0.25,
        "helpfulness": 0.15,
    })
    rules: dict[str, Any] = field(default_factory=lambda: {
        "require_abstain_on_low_confidence": True,
        "confidence_min": 0.55,
    })


@dataclass
class ToolPolicy:
    tools: list[str] = field(default_factory=list)
    allowlist_only: bool = True


@dataclass
class SkillSections:
    """Parsed markdown sections from SKILL.md body."""
    title: str = ""
    description_body: str = ""
    when_to_use: str = ""
    when_not_to_use: str = ""
    constraints: str = ""
    tools: str = ""
    output_format: str = ""
    examples: str = ""
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Skill:
    name: str
    path: Path
    skill_md: str
    active_version: str
    description: str = ""
    tools: ToolPolicy = field(default_factory=ToolPolicy)
    rubric: JudgeRubric = field(default_factory=JudgeRubric)
    frontmatter: dict[str, Any] = field(default_factory=dict)
    sections: SkillSections = field(default_factory=SkillSections)

    def compile_prompt(self) -> str:
        """Build the full LLM system prompt from structured SKILL.md sections."""
        parts: list[str] = []
        s = self.sections

        if s.title:
            parts.append(f"# {s.title}")
        if s.description_body:
            parts.append(s.description_body)

        if s.when_to_use:
            parts.append(f"## When to Use\n\n{s.when_to_use}")
        if s.when_not_to_use:
            parts.append(f"## When NOT to Use\n\n{s.when_not_to_use}")
        if s.constraints:
            parts.append(f"## Constraints\n\n{s.constraints}")
        if s.tools:
            parts.append(f"## Tools\n\n{s.tools}")
        if s.output_format:
            parts.append(f"## Output Format\n\n{s.output_format}")
        if s.examples:
            parts.append(f"## Examples\n\n{s.examples}")

        for heading, body in s.extra.items():
            parts.append(f"## {heading}\n\n{body}")

        return "\n\n".join(parts)

    def get_version_skill_md(self, version: str) -> str:
        vpath = self.path / "versions" / version / SKILL_FILENAME
        if not vpath.exists():
            raise FileNotFoundError(
                f"Version {version} not found for skill {self.name}"
            )
        return vpath.read_text()

    def list_versions(self) -> list[str]:
        versions_dir = self.path / "versions"
        if not versions_dir.exists():
            return []
        return sorted(
            [d.name for d in versions_dir.iterdir() if d.is_dir()],
            key=_version_sort_key,
        )

    def next_version(self) -> str:
        versions = self.list_versions()
        if not versions:
            return "v2"
        last = versions[-1]
        num = int(last.lstrip("v"))
        return f"v{num + 1}"

    def create_version(self, version: str, skill_md_text: str) -> Path:
        vdir = self.path / "versions" / version
        vdir.mkdir(parents=True, exist_ok=True)
        out = vdir / SKILL_FILENAME
        out.write_text(skill_md_text)
        return out

    def set_active_version(self, version: str) -> None:
        vpath = self.path / "versions" / version / SKILL_FILENAME
        if not vpath.exists():
            raise FileNotFoundError(
                f"Version {version} not found for skill {self.name}"
            )
        (self.path / ".active_version").write_text(version)
        self.active_version = version
        raw = vpath.read_text()
        self.skill_md = raw
        fm, sections = parse_skill_md(raw)
        self.frontmatter = fm
        self.sections = sections
        self._apply_frontmatter(fm)

    def previous_version(self) -> str | None:
        versions = self.list_versions()
        if len(versions) < 2:
            return None
        idx = (
            versions.index(self.active_version)
            if self.active_version in versions
            else -1
        )
        if idx <= 0:
            return None
        return versions[idx - 1]

    def _apply_frontmatter(self, fm: dict[str, Any]) -> None:
        self.description = fm.get("description", self.description)
        tool_list = fm.get("tools", [])
        if tool_list:
            self.tools = ToolPolicy(tools=tool_list, allowlist_only=True)
        judge_cfg = fm.get("judge", {})
        if judge_cfg:
            self.rubric = JudgeRubric(
                weights=judge_cfg.get("rubric", self.rubric.weights),
                rules=judge_cfg.get("rules", self.rubric.rules),
            )


# ---------------------------------------------------------------------------
# SKILL.md Parser
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

_SECTION_MAP: dict[str, str] = {
    "when to use": "when_to_use",
    "when not to use": "when_not_to_use",
    "constraints": "constraints",
    "tools": "tools",
    "output format": "output_format",
    "examples": "examples",
}


def parse_skill_md(text: str) -> tuple[dict[str, Any], SkillSections]:
    """Parse a SKILL.md file into (frontmatter_dict, SkillSections)."""
    fm: dict[str, Any] = {}
    body = text

    fm_match = _FRONTMATTER_RE.match(text)
    if fm_match:
        fm = yaml.safe_load(fm_match.group(1)) or {}
        body = text[fm_match.end():]

    sections = _parse_sections(body)
    return fm, sections


def _parse_sections(body: str) -> SkillSections:
    """Split markdown body into known sections by ## headings."""
    parts = re.split(r"^(#{1,2})\s+(.+)$", body, flags=re.MULTILINE)

    sections = SkillSections()
    preamble = parts[0].strip()
    if preamble:
        lines = preamble.split("\n", 1)
        title_line = lines[0].strip().lstrip("# ").strip()
        if title_line:
            sections.title = title_line
        if len(lines) > 1:
            sections.description_body = lines[1].strip()

    i = 1
    while i < len(parts) - 2:
        level = parts[i]
        heading = parts[i + 1].strip()
        content = parts[i + 2].strip() if i + 2 < len(parts) else ""
        i += 3

        if level == "#":
            sections.title = heading
            if content:
                sections.description_body = content
            continue

        key = heading.lower().strip()
        attr = _SECTION_MAP.get(key)
        if attr:
            setattr(sections, attr, content)
        else:
            sections.extra[heading] = content

    return sections


# ---------------------------------------------------------------------------
# Skill Loader
# ---------------------------------------------------------------------------

def _version_sort_key(v: str) -> int:
    try:
        return int(v.lstrip("v"))
    except ValueError:
        return 0


def load_skill(skill_dir: Path) -> Skill:
    """Load a single skill from its directory."""
    name = skill_dir.name
    skill_path = skill_dir / SKILL_FILENAME

    if not skill_path.exists():
        raise FileNotFoundError(
            f"No {SKILL_FILENAME} in skill directory: {skill_dir}"
        )

    raw = skill_path.read_text()

    active_version = "v1"
    av_path = skill_dir / ".active_version"
    if av_path.exists():
        active_version = av_path.read_text().strip()

    versioned = skill_dir / "versions" / active_version / SKILL_FILENAME
    if versioned.exists():
        raw = versioned.read_text()

    fm, sections = parse_skill_md(raw)

    tool_list = fm.get("tools", [])
    tools = ToolPolicy(tools=tool_list, allowlist_only=True)

    rubric = JudgeRubric()
    judge_cfg = fm.get("judge", {})
    if judge_cfg:
        rubric = JudgeRubric(
            weights=judge_cfg.get("rubric", rubric.weights),
            rules=judge_cfg.get("rules", rubric.rules),
        )

    v1_dir = skill_dir / "versions" / "v1"
    if not v1_dir.exists():
        v1_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_path, v1_dir / SKILL_FILENAME)

    return Skill(
        name=name,
        path=skill_dir,
        skill_md=raw,
        active_version=active_version,
        description=fm.get("description", ""),
        tools=tools,
        rubric=rubric,
        frontmatter=fm,
        sections=sections,
    )


class SkillRegistry:
    """Loads and manages all skills from a skills directory."""

    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, Skill] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self.skills_dir.exists():
            return
        for child in sorted(self.skills_dir.iterdir()):
            if child.is_dir() and (child / SKILL_FILENAME).exists():
                skill = load_skill(child)
                self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            raise KeyError(f"Skill not found: {name}")
        return self._skills[name]

    def list_skills(self) -> list[str]:
        return list(self._skills.keys())

    def all(self) -> dict[str, Skill]:
        return dict(self._skills)

    def reload(self, name: str) -> Skill:
        skill_dir = self.skills_dir / name
        skill = load_skill(skill_dir)
        self._skills[name] = skill
        return skill
