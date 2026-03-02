"""Promotion manager — promote, rollback, and track skill version changes."""

from __future__ import annotations

from evoagents.core.skill import Skill
from evoagents.core.store import TraceStore


def promote_skill(skill: Skill, patched_skill_md: str, store: TraceStore) -> str:
    """Promote a new SKILL.md version for a skill.

    Creates a new version directory, writes the SKILL.md, updates .active_version,
    and logs the promotion event.

    Returns the new version string.
    """
    old_version = skill.active_version
    new_version = skill.next_version()

    skill.create_version(new_version, patched_skill_md)
    skill.set_active_version(new_version)

    store.log_event("promotion", skill.name, {
        "from": old_version,
        "to": new_version,
    })

    return new_version


def rollback_skill(skill: Skill, store: TraceStore) -> str | None:
    """Rollback a skill to its previous version.

    Returns the version rolled back to, or None if no previous version exists.
    """
    prev = skill.previous_version()
    if prev is None:
        return None

    old_version = skill.active_version
    skill.set_active_version(prev)

    store.log_event("rollback", skill.name, {
        "from": old_version,
        "to": prev,
    })

    return prev
