"""Transform parsed member rows into a serializable summary dict.

>>> SEAM FOR FUTURE CUSTOM LOGIC <<<
This module is deliberately thin. The ``process`` function is where richer
guild analytics belong (e.g. top-N cut-offs, eligibility checks, role
recommendations). Today it produces a trivial-but-honest summary so the rest
of the pipeline (build -> static site -> Pages) is fully wired end-to-end.
Extend ``process`` (or add helpers here) without touching reader/build.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from . import config
from .reader import MemberRow


def _serialize_member(member: MemberRow) -> dict:
    """Convert a MemberRow (with nested SkillEntry dataclasses) to plain dict."""
    return asdict(member)


def _skill_summary(rows: list[MemberRow]) -> list[dict]:
    """Per-skill aggregate: average level and counts of tool/top/bot owned."""
    summary = []
    for skill in config.SKILLS:
        levels = [
            m.skills[skill].level
            for m in rows
            if skill in m.skills and m.skills[skill].level is not None
        ]
        tool_count = sum(1 for m in rows if m.skills.get(skill) and m.skills[skill].tool)
        top_count = sum(1 for m in rows if m.skills.get(skill) and m.skills[skill].top)
        bot_count = sum(1 for m in rows if m.skills.get(skill) and m.skills[skill].bot)

        avg = round(sum(levels) / len(levels), 1) if levels else None
        summary.append(
            {
                "skill": skill,
                "average_level": avg,
                "levels_reported": len(levels),
                "tool_count": tool_count,
                "top_count": top_count,
                "bot_count": bot_count,
            }
        )
    return summary


def process(rows: list[MemberRow]) -> dict:
    """Produce the output payload rendered by ``build.py``.

    Returns a dict with:
      - generated_at: UTC ISO-8601 timestamp
      - member_count: number of parsed members
      - skills: ordered skill name list (for stable table columns)
      - skill_summary: per-skill averages and tool/top/bot counts
      - members: serialized member rows
    """
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "member_count": len(rows),
        "skills": list(config.SKILLS),
        "skill_summary": _skill_summary(rows),
        "members": [_serialize_member(m) for m in rows],
    }
