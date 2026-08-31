"""The synthetic roster behind the golden pre-roster week.

Kept in its own module, with NO imports from src beyond the two dataclasses, so
that the same file can be copied into a git worktree of the pre-change commit and
run there to GENERATE the golden — which is what makes
``test_roster_disabled_reproduces_the_golden_week`` a comparison against the old
code rather than against itself.

Everything here is fixed: a seeded RNG, a fixed draw, a fixed party cap. Nothing
reads the clock, the network or the sheet.
"""

from __future__ import annotations

import random

from src.reader import MemberRow, SkillEntry

SKILLS = [
    "Milking", "Foraging", "Woodcutting", "C.Smithing", "Crafting",
    "Tailoring", "Cooking", "Brewing", "Bell Farming", "Enhancing",
]

# The golden week's fixed parameters. Not read from config: config is allowed to
# change, and this golden pins the RACE, not the configuration.
GOLDEN_DRAW = ["Milking", "Enhancing", "Cooking", "Brewing"]
GOLDEN_SEED = 42
GOLDEN_CAP = 20
GOLDEN_STRATEGY = "best"
GOLDEN_MEMBERS = 30


def golden_members() -> list[MemberRow]:
    """Thirty deterministic members, spread widely enough to rank distinctly."""
    rng = random.Random(20260831)
    members: list[MemberRow] = []
    for i in range(GOLDEN_MEMBERS):
        skills = {}
        for skill in SKILLS:
            skills[skill] = SkillEntry(
                level=rng.randint(70, 130),
                tool=rng.random() < 0.3,
                top=rng.random() < 0.4,
                bot=rng.random() < 0.4,
                # A third of the H cells blank, so DEFAULT_HOUSE_LEVEL is
                # exercised too.
                house=(None if rng.random() < 0.33 else rng.randint(0, 8)),
            )
        members.append(
            MemberRow(
                name=f"member{i:02d}",
                main_classes="",
                flex="",
                flex_levels=[],
                skills=skills,
            )
        )
    return members
