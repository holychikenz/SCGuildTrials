"""Guild-trials scoring model, tier-race simulator, and random assignment.

Phase 1 of the guild-trials feature. This module is PURE LOGIC — no HTML, no
network, no file I/O. ``build.py`` fetches live member data (via ``scraper``),
calls into here, then renders the page.

The model is documented in ``research/trial-messages.md`` (mechanics, the
CORRECTION and WORKING ASSUMPTION sections) and the equipment constants in
``research/item-stats.md`` / ``research/item-stats.json``. Every numeric
constant lives in :mod:`src.config` with an in-line citation.

Model summary (per member ``m``, trial skill ``s``, tier ``t``)::

    tierLevel(t)        = 100 + 10*(t-1)
    baseTarget(t)       = tierLevel(t) * 10
    effectiveTarget(t,N)= baseTarget(t) * (1 + 0.01*N) * TARGET_SCALE
    delta(m,t)          = level_m - tierLevel(t)
    levelBonus          = delta*0.005 if delta >= 0 else delta*0.01
    success(m,t)        = clamp(0.8 * (1 + levelBonus + successBonus_m), 0, 1)
    workPower(m)        = level_m * (1 + efficiency_m)
    actionSeconds(m)    = baseActionSeconds / (1 + speed_m)
    rate(m,t)           = success(m,t) * floor(workPower(m)) / actionSeconds(m)
    timeToClear(t)      = effectiveTarget(t,N) / sum_m rate(m,t)
    tier reached        = max T with sum_{t=1..T} timeToClear(t) <= 3600

Enhancing is special: its tool grants SUCCESS (not speed), and its family
"gloves" grant SPEED (not efficiency); its base action time is 8s not 10s.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import config
from .reader import MemberRow


# ---------------------------------------------------------------------------
# Equipment / level resolution
# ---------------------------------------------------------------------------
@dataclass
class MemberBonuses:
    """Resolved skilling bonuses for one member in one trial skill."""

    level: Optional[int]        # resolved skill level (from the sheet column)
    speed: float                # summed speed bonus (fraction)
    efficiency: float           # summed efficiency bonus (fraction)
    success_bonus: float        # additive success bonus (enhancing tool only)
    tool: bool                  # celestial tool checkbox (else holy baseline)
    top: bool
    bot: bool


def _is_enhancing(skill: str) -> bool:
    return skill == "Enhancing"


def _is_gathering(skill: str) -> bool:
    """Gathering-family skill (Milking/Foraging/Woodcutting).

    The community gathering buff — modelled as the doubling chance — applies to
    this family only (config.GATHERING_SKILLS).
    """
    return skill in config.GATHERING_SKILLS


def double_chance(skill: str) -> float:
    """Labyrinth-style doubleProgressChance for a member on ``skill``.

    While the community gathering buff is live, gathering skills carry the +20%
    buff plus ~+5% gear (config.DOUBLE_CHANCE); every other family carries 0.
    Scales work rate by ``(1 + double_chance)`` in :func:`rate`, per the lab-sim
    formula (research/trial-messages.md).
    """
    return config.DOUBLE_CHANCE if _is_gathering(skill) else 0.0


def _sheet_column(skill: str) -> str:
    """Map a trial skill name to its member-sheet column name.

    Identity for every skill except "Alchemy", which reads the "Bell Farming"
    column — the guild's in-joke column name that actually records Alchemy
    levels (see config.TRIAL_SKILL_TO_SHEET_COLUMN).
    """
    return config.TRIAL_SKILL_TO_SHEET_COLUMN.get(skill, skill)


def _resolve_level_and_checks(
    member: MemberRow, skill: str
) -> tuple[Optional[int], bool, bool, bool, Optional[int]]:
    """Return (level, tool, top, bot, house) for a member+trial-skill.

    The level, checkboxes, and per-skill house level come straight from the
    member sheet column that the trial skill maps to. "Alchemy" maps to the
    "Bell Farming" column (the guild joke — that column IS Alchemy); every other
    skill maps to its own column. A member with no such column contributes
    nothing (and a blank house cell -> None).
    """
    entry = member.skills.get(_sheet_column(skill))
    if entry is None:
        return None, False, False, False, None
    return entry.level, entry.tool, entry.top, entry.bot, entry.house


def _house_level(house: Optional[int]) -> int:
    """Resolve a member's per-skill house level for the model.

    Blank (None) -> DEFAULT_HOUSE_LEVEL (the former flat assumption of 4);
    otherwise the sheet value, clamped to the in-game range 0..8.
    """
    if house is None:
        house = config.DEFAULT_HOUSE_LEVEL
    return max(0, min(config.HOUSE_MAX_LEVEL, house))


def member_bonuses(member: MemberRow, skill: str) -> MemberBonuses:
    """Compute the summed speed/efficiency/success bonuses for member+skill.

    Equipment baseline (research/trial-tabs.md + item-stats.md):
      - Tool: celestial +7 if the member's "tool" checkbox is TRUE, else holy
        +7. For the 9 non-enhancing skills the tool grants SPEED; for ENHANCING
        it grants SUCCESS.
      - Cape +3 (everyone): +0.0665 speed.
      - Family piece +7 (everyone): +0.1182 efficiency for the covering piece
        (Collector's Boots / Enchanted Gloves / Eye Watch / Red Culinary Hat).
        ENHANCING special case: the gloves grant +0.1182 enhancingSPEED instead.
      - Skilling top +7 if "top": +0.1182 efficiency.
      - Skilling bottom +7 if "bot": +0.1182 efficiency.
      - House (per-skill "H" level from the sheet): +0.015 efficiency/level for
        gathering + production; the enhancing house grants +0.010 speed/level
        instead. Blank -> DEFAULT_HOUSE_LEVEL (4), clamped to 0..8.
    """
    level, tool, top, bot, house = _resolve_level_and_checks(member, skill)
    house_level = _house_level(house)

    speed = config.CAPE_SPEED_PLUS3  # +3 cape speed, everyone, every skill
    efficiency = 0.0
    success_bonus = 0.0

    if _is_enhancing(skill):
        # Tool grants SUCCESS, not speed.
        success_bonus += (
            config.TOOL_SUCCESS_CELESTIAL_PLUS7
            if tool
            else config.TOOL_SUCCESS_HOLY_PLUS7
        )
        # Family "gloves" grant enhancing SPEED, not efficiency.
        speed += config.GLOVES_ENHANCING_SPEED_PLUS7
        # Community enhancing-speed buff (event): +0.20 speed while live.
        speed += config.COMMUNITY_ENHANCING_SPEED_BUFF
        # Enhancing house (Observatory) grants action-SPEED, not efficiency,
        # scaled by the member's real house level (0.010/level).
        speed += config.HOUSE_ENHANCING_SPEED_PER_LEVEL * house_level
    else:
        # Tool grants SPEED.
        speed += (
            config.TOOL_SPEED_CELESTIAL_PLUS7
            if tool
            else config.TOOL_SPEED_HOLY_PLUS7
        )
        # Family piece grants efficiency.
        efficiency += config.ARMOUR_EFFICIENCY_PLUS7
        # Gathering + production house rooms grant efficiency (0.015/level),
        # scaled by the member's real house level.
        efficiency += config.HOUSE_EFFICIENCY_PER_LEVEL * house_level
        # Community production-efficiency buff (event): +0.15 efficiency for
        # production skills while live. Gathering skills instead receive the
        # gathering buff as a doubling chance (see double_chance()), so exclude
        # them here.
        if not _is_gathering(skill):
            efficiency += config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF

    # Skilling top / bottom grant efficiency for every skill (per the Phase 1
    # model spec). NB: in-game the Enhancer's Top/Bottoms grant enhancingSpeed
    # rather than efficiency; the Phase 1 model deliberately treats top/bot as
    # efficiency uniformly — see the trials-page footnotes.
    if top:
        efficiency += config.ARMOUR_EFFICIENCY_PLUS7
    if bot:
        efficiency += config.ARMOUR_EFFICIENCY_PLUS7

    return MemberBonuses(
        level=level,
        speed=speed,
        efficiency=efficiency,
        success_bonus=success_bonus,
        tool=tool,
        top=top,
        bot=bot,
    )


# ---------------------------------------------------------------------------
# Per-tier math
# ---------------------------------------------------------------------------
def tier_level(tier: int) -> int:
    """tierLevel(t) = 100 + 10*(t-1)."""
    return config.TIER_BASE_LEVEL + config.TIER_LEVEL_STEP * (tier - 1)


def base_target(tier: int) -> float:
    """baseTarget(t) = DifficultyLevel(t) * 400 (Orvel's TotalWork coefficient)."""
    return tier_level(tier) * config.TIER_TARGET_PER_LEVEL


def effective_target(tier: int, party_size: int, target_scale: float) -> float:
    """TotalWork(t, N) = DifficultyLevel(t) * 400 * (1 + N/100).

    Expressed as ``baseTarget(t) * (1 + 0.01*N) * TARGET_SCALE`` with
    TARGET_SCALE pinned to 1.0 (the 400 coefficient carries the scaling); the
    scale override is retained only for a possible future recalibration.
    """
    penalty = 1.0 + config.HEADCOUNT_PENALTY_PER_MEMBER * party_size
    return base_target(tier) * penalty * target_scale


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def success(level: int, tier: int, success_bonus: float) -> float:
    """Per-action success rate, per Orvel's confirmed formula.

    ``delta = SkillLevel + BuildingSkillLevels - DifficultyLevel`` (the tier
    level); the per-level slope is +0.005 when the effective level meets or
    exceeds the difficulty and -0.01 (a steeper penalty) when it falls short.
    For Enhancing, ``success_bonus`` carries the EnhancingSuccessRate (enhancer
    tool success + Observatory enhancing-success (0 in live data) + achievement
    bonus). Floored at 0.05 (MAX(0.05, ...)) and capped at 1.0.
    """
    effective_level = level + config.BUILDING_SKILL_LEVELS
    delta = effective_level - tier_level(tier)
    if delta >= 0:
        level_bonus = delta * config.LEVEL_BONUS_POS
    else:
        level_bonus = delta * config.LEVEL_BONUS_NEG
    return _clamp(
        config.SUCCESS_BASE * (1 + level_bonus + success_bonus),
        config.SUCCESS_FLOOR,
        1.0,
    )


def work_power(level: int, efficiency: float) -> float:
    """workPower(m) = level * (1 + efficiency)."""
    return level * (1 + efficiency)


def action_seconds(skill: str, speed: float) -> float:
    """actionSeconds(m) = baseActionSeconds / (1 + speed)."""
    base = (
        config.ACTION_SECONDS_ENHANCING
        if _is_enhancing(skill)
        else config.ACTION_SECONDS_DEFAULT
    )
    return base / (1 + speed)


def rate(member: MemberRow, skill: str, tier: int) -> float:
    """Work per second contributed by ``member`` to ``skill`` at ``tier``.

    Follows the lab-sim formula
    ``rate = success * (1 + doubleChance) * floor(workPower) / actionSeconds``.
    The doubling chance is non-zero only for gathering skills while the
    community gathering buff is live (see :func:`double_chance`). A member with
    no usable level in the skill contributes 0.
    """
    b = member_bonuses(member, skill)
    if not b.level or b.level <= 0:
        return 0.0
    s = success(b.level, tier, b.success_bonus)
    wp = math.floor(work_power(b.level, b.efficiency))
    return s * (1 + double_chance(skill)) * wp / action_seconds(skill, b.speed)


def points_for_tier(tier_reached: int) -> int:
    """points(T) = 100 + 100*T for T >= 1, else 0.

    ASSUMPTION (flagged): matches the only observed data points
    (milking tier1 -> 200, tier2 -> 300; research/trial-messages.md).
    """
    return 100 + 100 * tier_reached if tier_reached >= 1 else 0


# ---------------------------------------------------------------------------
# Simulation result types
# ---------------------------------------------------------------------------
@dataclass
class TierStep:
    """One tier's outcome in the cumulative race."""

    tier: int
    tier_level: int
    effective_target: float
    party_rate: float
    time_to_clear: Optional[float]   # None when the party rate is 0
    cumulative_time: Optional[float]  # would-be cumulative including this tier
    cleared: bool


@dataclass
class RosterEntry:
    """One member's contribution summary within a trial party."""

    name: str
    level: Optional[int]
    tool: bool
    top: bool
    bot: bool
    rate_tier1: float
    rate_final: float  # rate at the final tier reached (or tier 1 if none)


@dataclass
class TrialResult:
    """The full result of one skilling trial's tier race."""

    skill: str
    party_size: int
    tier_reached: int
    points: int
    roster: list[RosterEntry] = field(default_factory=list)
    timeline: list[TierStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# Safety bound: success is now floored at 0.05 (it never reaches 0), but the
# per-tier target grows without bound (DifficultyLevel * 400 * ...) while party
# rate is bounded, so cumulative time exceeds the 1-hour budget and the race
# always terminates. This cap only guards against a pathological all-superhuman
# party that never exhausts the budget.
_MAX_TIER = 100


def simulate_race(
    party: list[MemberRow], skill: str, target_scale: Optional[float] = None
) -> TrialResult:
    """Simulate the 1-hour cumulative tier race for ``party`` in ``skill``.

    The party races upward from tier 1, spending the shared
    ``TRIAL_TIME_BUDGET_SECONDS`` budget; the recorded outcome is the highest
    tier fully cleared within budget. The returned timeline runs up to and
    including the first tier NOT cleared (the failed tier), so the page can show
    where the party ran out of time.
    """
    if target_scale is None:
        target_scale = config.TARGET_SCALE

    n = len(party)
    budget = config.TRIAL_TIME_BUDGET_SECONDS
    timeline: list[TierStep] = []
    cumulative = 0.0
    tier_reached = 0

    tier = 1
    while tier <= _MAX_TIER:
        party_rate = sum(rate(m, skill, tier) for m in party)
        eff_target = effective_target(tier, n, target_scale)

        if party_rate <= 0:
            # No forward progress possible at this tier: record a failed step.
            timeline.append(
                TierStep(
                    tier=tier,
                    tier_level=tier_level(tier),
                    effective_target=eff_target,
                    party_rate=party_rate,
                    time_to_clear=None,
                    cumulative_time=None,
                    cleared=False,
                )
            )
            break

        ttc = eff_target / party_rate
        would_be = cumulative + ttc
        cleared = would_be <= budget
        timeline.append(
            TierStep(
                tier=tier,
                tier_level=tier_level(tier),
                effective_target=eff_target,
                party_rate=party_rate,
                time_to_clear=ttc,
                cumulative_time=would_be,
                cleared=cleared,
            )
        )
        if not cleared:
            break
        cumulative = would_be
        tier_reached = tier
        tier += 1

    final_tier = tier_reached if tier_reached >= 1 else 1
    roster = [
        RosterEntry(
            name=m.name,
            level=member_bonuses(m, skill).level,
            tool=member_bonuses(m, skill).tool,
            top=member_bonuses(m, skill).top,
            bot=member_bonuses(m, skill).bot,
            rate_tier1=rate(m, skill, 1),
            rate_final=rate(m, skill, final_tier),
        )
        for m in party
    ]

    return TrialResult(
        skill=skill,
        party_size=n,
        tier_reached=tier_reached,
        points=points_for_tier(tier_reached),
        roster=roster,
        timeline=timeline,
    )


# ---------------------------------------------------------------------------
# Random assignment (Phase 1 — NO optimizer)
# ---------------------------------------------------------------------------
@dataclass
class Assignment:
    """A random split of members into per-skill parties plus a bench."""

    parties: dict[str, list[MemberRow]]
    bench: list[MemberRow]


def random_assignment(
    members: list[MemberRow],
    skills: list[str],
    seed: int,
    cap: int = 20,
) -> Assignment:
    """Randomly split ``members`` into one party (<= ``cap``) per skill.

    Deterministic given ``seed`` (uses ``random.Random(seed)`` — never unseeded
    randomness). Members are shuffled once, then handed out in contiguous
    chunks of ``cap`` in ``skills`` order; anyone past ``len(skills) * cap``
    lands on the bench. This is a plain random split — there is NO optimizer and
    NO eligibility filtering in Phase 1 (that is Phase 2).
    """
    rng = random.Random(seed)
    shuffled = list(members)
    rng.shuffle(shuffled)

    parties: dict[str, list[MemberRow]] = {}
    idx = 0
    for skill in skills:
        parties[skill] = shuffled[idx : idx + cap]
        idx += cap
    bench = shuffled[idx:]
    return Assignment(parties=parties, bench=bench)


# ---------------------------------------------------------------------------
# Week orchestration (convenience for the build; still pure logic)
# ---------------------------------------------------------------------------
@dataclass
class WeekResult:
    """Everything the trials page needs for one week's draw."""

    generated_at: str
    week_date: str
    skills: list[str]
    seed: int
    cap: int
    target_scale: float
    member_count: int
    total_points: int
    strategy: str = "random"
    trials: list[TrialResult] = field(default_factory=list)
    bench: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "week_date": self.week_date,
            "skills": self.skills,
            "seed": self.seed,
            "cap": self.cap,
            "target_scale": self.target_scale,
            "member_count": self.member_count,
            "total_points": self.total_points,
            "strategy": self.strategy,
            "trials": [t.to_dict() for t in self.trials],
            "bench": self.bench,
        }


def run_week(
    members: list[MemberRow],
    skills: Optional[list[str]] = None,
    seed: Optional[int] = None,
    cap: Optional[int] = None,
    target_scale: Optional[float] = None,
    strategy: Optional[str] = None,
) -> WeekResult:
    """Assign parties and simulate all of this week's skilling trials.

    ``strategy`` selects the Phase 2 assignment algorithm (see
    :mod:`src.optimizer`); ``"random"`` restores the Phase 1 shuffle. Defaults to
    ``config.TRIAL_OPTIMIZER_STRATEGY``. The optimizer is imported lazily to keep
    the ``trials`` <-> ``optimizer`` dependency one-directional at import time.
    """
    skills = list(skills if skills is not None else config.TRIAL_SKILLS_CURRENT)
    seed = seed if seed is not None else config.TRIAL_RNG_SEED
    cap = cap if cap is not None else config.TRIAL_PARTY_CAP
    if target_scale is None:
        target_scale = config.TARGET_SCALE
    if strategy is None:
        strategy = config.TRIAL_OPTIMIZER_STRATEGY

    if strategy == "random":
        assignment = random_assignment(members, skills, seed, cap)
    else:
        from .optimizer import optimize

        assignment = optimize(
            members,
            skills,
            seed=config.TRIAL_OPTIMIZER_SEED,
            cap=cap,
            target_scale=target_scale,
            strategy=strategy,
        )

    trials = [
        simulate_race(assignment.parties[skill], skill, target_scale)
        for skill in skills
    ]
    now = datetime.now(timezone.utc)
    return WeekResult(
        generated_at=now.isoformat(),
        week_date=now.strftime("%Y-%m-%d"),
        skills=skills,
        seed=seed,
        cap=cap,
        target_scale=target_scale,
        member_count=len(members),
        total_points=sum(t.points for t in trials),
        strategy=strategy,
        trials=trials,
        bench=[m.name for m in assignment.bench],
    )
