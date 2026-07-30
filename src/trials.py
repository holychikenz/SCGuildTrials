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
    baseTarget(t)       = tierLevel(t) * 400
    effectiveTarget(t,N)= baseTarget(t) * (1 + 0.01*N) * TARGET_SCALE
    delta(m,s,t)        = level_m + guildBuildingLevels(s) - tierLevel(t)
    levelBonus          = delta*0.005 if delta >= 0 else delta*0.01
    success(m,t)        = clamp(0.8 * (1 + levelBonus + successBonus_m), 0, 1)
    workPower(m)        = level_m * (1 + efficiency_m)   # own level only
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
    # Guild-wide, NOT per-member: skill levels granted by the guild's building
    # for this skill (+2 per building level). Resolved here so that
    # member_bonuses stays the single place where a member+skill's bonuses are
    # assembled; see guild_building_skill_levels.
    building_levels: int = 0


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


def guild_building_level(skill: str) -> int:
    """The guild's BUILDING level (0..20) for ``skill``'s building.

    Read from ``config.GUILD_BUILDING_LEVELS`` and clamped to
    0..``GUILD_BUILDING_MAX_LEVEL``, so a typo'd or stale entry can never inflate
    the model without bound. Unknown / omitted / None skills read as 0.
    """
    level = config.GUILD_BUILDING_LEVELS.get(skill) or 0
    return max(0, min(config.GUILD_BUILDING_MAX_LEVEL, level))


def building_skill_levels(building_level: int) -> int:
    """SKILL levels granted by a building at ``building_level``.

    ``+2 per building level`` (``flatBoost == flatBoostLevelBonus == 2`` in
    ``guildBuildingDetailMap``), i.e. up to +40 at the level-20 cap. Takes the
    building level explicitly so hypothetical upgrades can be priced without
    touching the config — see :func:`probe_building_upgrade`.
    """
    level = max(0, min(config.GUILD_BUILDING_MAX_LEVEL, building_level))
    return config.GUILD_BUILDING_SKILL_LEVELS_PER_LEVEL * level


def guild_building_skill_levels(skill: str) -> int:
    """Skill levels the guild's building for ``skill`` grants to EVERY member.

    Guild buildings (game data ``guildBuildingDetailMap``) are distinct from the
    per-member house rooms: each of the ten skilling buildings carries a
    ``/buff_types/<skill>_level`` buff worth ``+2 levels per building level``, so
    this is simply :func:`building_skill_levels` of the guild's current
    :func:`guild_building_level` (0 for every skill today — no skilling guild
    building is built).
    """
    return building_skill_levels(guild_building_level(skill))


def guild_building_upgrade_cost(to_level: int) -> Optional[int]:
    """Guild points to raise a skilling building TO ``to_level`` (one step).

    Straight from ``config.GUILD_BUILDING_POINT_COSTS`` (the game's
    ``guildPointCosts``), so upgrading from level L costs
    ``guild_building_upgrade_cost(L + 1)`` — 500 for an unbuilt building's first
    level. Returns None beyond the level-20 cap.
    """
    return config.GUILD_BUILDING_POINT_COSTS.get(to_level)


def member_bonuses(
    member: MemberRow, skill: str, building_levels: Optional[int] = None
) -> MemberBonuses:
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
      - Guild building (guild-wide, not per-member): +2 SKILL LEVELS per building
        level, carried on ``building_levels`` and added to the member's own level
        in :func:`success` (see :func:`guild_building_skill_levels`).

    ``building_levels`` overrides the guild-building contribution (in granted
    SKILL levels, not building levels) instead of reading it from the config —
    used to price a hypothetical upgrade without mutating global state. None
    means "use the guild's actual building".
    """
    level, tool, top, bot, house = _resolve_level_and_checks(member, skill)
    house_level = _house_level(house)
    if building_levels is None:
        building_levels = guild_building_skill_levels(skill)

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
        building_levels=building_levels,
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


def success(
    level: int, tier: int, success_bonus: float, building_levels: int = 0
) -> float:
    """Per-action success rate, per Orvel's confirmed formula.

    ``delta = SkillLevel + BuildingSkillLevels - DifficultyLevel`` (the tier
    level); the per-level slope is +0.005 when the effective level meets or
    exceeds the difficulty and -0.01 (a steeper penalty) when it falls short.
    For Enhancing, ``success_bonus`` carries the EnhancingSuccessRate (enhancer
    tool success + Observatory enhancing-success (0 in live data) + achievement
    bonus). Floored at 0.05 (MAX(0.05, ...)) and capped at 1.0.

    ``building_levels`` is the BuildingSkillLevels term: the levels the guild's
    building for this skill grants every member (+2 per building level). It is
    an explicit argument rather than a config lookup because this function is
    deliberately skill-agnostic; :func:`rate` supplies it from
    :func:`member_bonuses`. It defaults to 0 so direct callers keep the bare
    "own level only" behaviour.
    """
    effective_level = level + building_levels
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
    """workPower(m) = level * (1 + efficiency).

    NB: ``level`` is the member's OWN sheet level — guild-building skill levels
    are deliberately NOT included. Orvel's confirmed formula names
    BuildingSkillLevels only in the success delta, and no capture yet shows
    ``progressPerAction`` rising with a guild building. If one does, pass the
    effective level here too (see config's guild-buildings section).
    """
    return level * (1 + efficiency)


def action_seconds(skill: str, speed: float) -> float:
    """actionSeconds(m) = baseActionSeconds / (1 + speed)."""
    base = (
        config.ACTION_SECONDS_ENHANCING
        if _is_enhancing(skill)
        else config.ACTION_SECONDS_DEFAULT
    )
    return base / (1 + speed)


def _prepare_member(
    member: MemberRow, skill: str, building_levels: int
) -> Optional[tuple[int, float, int, float, int, float]]:
    """Precompute everything about member+skill that does NOT depend on the tier.

    Returns ``(level, success_bonus, building_levels, double_factor, work_power,
    action_seconds)`` — every input :func:`rate` needs except the tier. The
    per-tier rate is then
    ``success(level, tier, success_bonus, building) * double_factor * work_power
    / action_seconds``.

    Returns None for a member with no usable level in the skill (they contribute
    nothing, so callers drop them from the party loop entirely).

    WHY THIS EXISTS: the optimizer evaluates ~87k races per pipeline, each racing
    ~13 tiers, which called :func:`rate` — and through it the whole equipment
    bonus assembly — 22.3 MILLION times to compute about 1,200 distinct values.
    Hoisting the tier-independent part out of the loop is worth several minutes of
    build time (see the PERFORMANCE note in simulate_race). A plain tuple rather
    than a dataclass because the caller unpacks it in the hottest loop in the
    project, where attribute lookups are measurable.

    BIT-EXACTNESS: the three factors are returned SEPARATELY, not pre-multiplied
    into a single throughput, so callers can evaluate them in the original
    ``success * double * workPower / actionSeconds`` order. Folding them into one
    constant re-associates the arithmetic, and a resulting one-ULP difference in a
    party rate is enough to send the search down a different path — observed
    live: SC kept its 4800 points but reshuffled every party for no gain. Same
    values in the same order means the optimizer's trajectory is untouched.
    """
    b = member_bonuses(member, skill, building_levels)
    if not b.level or b.level <= 0:
        return None
    return (
        b.level,
        b.success_bonus,
        b.building_levels,
        1 + double_chance(skill),
        math.floor(work_power(b.level, b.efficiency)),
        action_seconds(skill, b.speed),
    )


def rate(
    member: MemberRow,
    skill: str,
    tier: int,
    building_levels: Optional[int] = None,
) -> float:
    """Work per second contributed by ``member`` to ``skill`` at ``tier``.

    Follows the lab-sim formula
    ``rate = success * (1 + doubleChance) * floor(workPower) / actionSeconds``.
    The doubling chance is non-zero only for gathering skills while the
    community gathering buff is live (see :func:`double_chance`). The guild
    building's skill levels raise the success term only, never work power. A
    member with no usable level in the skill contributes 0 — a guild building
    cannot conjure a party from members who have not trained the skill.

    ``building_levels`` (granted skill levels) overrides the guild-building term;
    None uses the guild's actual building — resolve it ONCE in the caller and
    pass it in when calling this in a loop.

    This is the per-member convenience form. Race simulation goes through
    :func:`_prepare_member` instead, which hoists everything tier-independent out
    of the loop.
    """
    if building_levels is None:
        building_levels = guild_building_skill_levels(skill)
    prepared = _prepare_member(member, skill, building_levels)
    if prepared is None:
        return 0.0
    level, success_bonus, building, double, wp, asec = prepared
    return success(level, tier, success_bonus, building) * double * wp / asec


def points_for_tier(tier_reached: int) -> int:
    """points(T) = 100 + 100*T for T >= 1, else 0.

    ASSUMPTION (flagged): matches the only observed data points
    (milking tier1 -> 200, tier2 -> 300; research/trial-messages.md).

    The slope (``config.TRIAL_POINTS_PER_TIER``) is what one extra tier is worth,
    and the upgrade probe prices building levels against it — hence the named
    constants rather than two literal 100s.
    """
    if tier_reached < 1:
        return 0
    return config.TRIAL_POINTS_BASE + config.TRIAL_POINTS_PER_TIER * tier_reached


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
    party: list[MemberRow],
    skill: str,
    target_scale: Optional[float] = None,
    building_levels: Optional[int] = None,
) -> TrialResult:
    """Simulate the 1-hour cumulative tier race for ``party`` in ``skill``.

    The party races upward from tier 1, spending the shared
    ``TRIAL_TIME_BUDGET_SECONDS`` budget; the recorded outcome is the highest
    tier fully cleared within budget. The returned timeline runs up to and
    including the first tier NOT cleared (the failed tier), so the page can show
    where the party ran out of time.

    ``building_levels`` (granted skill levels) overrides the guild-building term
    for the whole party — the mechanism behind
    :func:`probe_building_upgrade`. None uses the guild's actual building.

    PERFORMANCE: this is the optimizer's oracle, called ~87k times per pipeline,
    so everything that does not vary with the tier is hoisted out of the tier loop
    — the guild-building lookup once per race, and each member's equipment bonuses
    once per race (:func:`_prepare_member`) rather than once per member per tier.
    The tier loop is then one :func:`success` call and three float operations per
    member.
    Members with no usable level are dropped from the loop entirely: they
    contribute exactly 0, but they still count toward the headcount penalty ``n``,
    so the length of ``party`` — not of the prepared list — sets the work target.
    """
    if target_scale is None:
        target_scale = config.TARGET_SCALE
    if building_levels is None:
        building_levels = guild_building_skill_levels(skill)

    n = len(party)
    budget = config.TRIAL_TIME_BUDGET_SECONDS
    timeline: list[TierStep] = []
    cumulative = 0.0
    tier_reached = 0

    # Tier-independent per-member factors, computed once for the whole race.
    prepared = [
        p
        for p in (_prepare_member(m, skill, building_levels) for m in party)
        if p is not None
    ]

    tier = 1
    while tier <= _MAX_TIER:
        # Same factor order as rate(), and summed with sum() rather than a manual
        # accumulator — BOTH deliberate. Re-associating the factors shifts the
        # last bit, and since CPython 3.12 sum() applies Neumaier compensation to
        # float sequences, a hand-rolled `+=` loop is a *different* (naive) sum.
        # Either change perturbs the party rate by ~1 ULP, which is enough to send
        # the optimizer down a different path: observed live, SC kept its 4800
        # points but reshuffled every party for no gain. See _prepare_member.
        party_rate = sum(
            success(level, tier, success_bonus, building) * double * wp / asec
            for level, success_bonus, building, double, wp, asec in prepared
        )
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
    # One member_bonuses per member (it used to be called four times each), and
    # the two reported rates reuse the prepared factors.
    roster = []
    for m in party:
        b = member_bonuses(m, skill, building_levels)
        p = _prepare_member(m, skill, building_levels)
        if p is None:
            rate_tier1 = rate_final = 0.0
        else:
            level, success_bonus, building, double, wp, asec = p
            rate_tier1 = (
                success(level, 1, success_bonus, building) * double * wp / asec
            )
            rate_final = (
                success(level, final_tier, success_bonus, building)
                * double
                * wp
                / asec
            )
        roster.append(
            RosterEntry(
                name=m.name,
                level=b.level,
                tool=b.tool,
                top=b.top,
                bot=b.bot,
                rate_tier1=rate_tier1,
                rate_final=rate_final,
            )
        )

    return TrialResult(
        skill=skill,
        party_size=n,
        tier_reached=tier_reached,
        points=points_for_tier(tier_reached),
        roster=roster,
        timeline=timeline,
    )


# ---------------------------------------------------------------------------
# Guild-building upgrade probe ("what does the next tier cost, and when does it
# pay for itself?")
# ---------------------------------------------------------------------------
def guild_building_upgrade_total_cost(
    from_level: int, to_level: int
) -> Optional[int]:
    """Cumulative guild points to raise a building from ``from_level`` to ``to_level``.

    The game prices each LEVEL, never the jump, so a multi-level upgrade costs the
    sum of every step in between::

        sum(GUILD_BUILDING_POINT_COSTS[L] for L in from_level+1 .. to_level)

    Returns 0 for a no-op (``to_level <= from_level``) and None if ANY step in the
    range is unpriced — i.e. the range runs past the level-20 cap — so a caller
    can never quote a silently truncated total.
    """
    if to_level <= from_level:
        return 0
    total = 0
    for level in range(from_level + 1, to_level + 1):
        step = guild_building_upgrade_cost(level)
        if step is None:
            return None
        total += step
    return total


def upgrade_payback_draws(
    cost: Optional[int], points_gained: int
) -> Optional[float]:
    """How many DRAWS of a skill it takes to earn ``cost`` guild points back.

    A tier bought with guild points pays out only when the trial is actually run,
    and then it pays ``points_gained`` (one tier is worth
    ``config.TRIAL_POINTS_PER_TIER``), so ``draws = cost / points_gained``.
    Returns None when there is nothing to price: no cost, or no points gained (in
    which case the spend never returns at all — not "returns in 0 draws").
    """
    if cost is None or points_gained <= 0:
        return None
    return cost / points_gained


def upgrade_payback_weeks(
    cost: Optional[int],
    points_gained: int,
    weeks_between_draws: Optional[float] = None,
) -> Optional[float]:
    """Weeks for a one-off ``cost`` in guild points to earn itself back.

    :func:`upgrade_payback_draws` in calendar terms: any one skill is drawn every
    ``config.TRIAL_WEEKS_BETWEEN_DRAWS`` weeks on average (four of the ten skills
    per week, so 2.5), hence::

        weeks_to_return = (cost / points_gained) * weeks_between_draws

    ASSUMPTION (optimistic, flagged in config and on the page): the bought tier is
    assumed to be earned EVERY time the skill comes up. None when the cost cannot
    return (see :func:`upgrade_payback_draws`).
    """
    draws = upgrade_payback_draws(cost, points_gained)
    if draws is None:
        return None
    if weeks_between_draws is None:
        weeks_between_draws = config.TRIAL_WEEKS_BETWEEN_DRAWS
    return draws * weeks_between_draws


@dataclass
class BuildingUpgrade:
    """What it would take for one guild building to buy one trial another tier.

    Three questions per drawn skill: HOW MANY building levels are needed to gain a
    tier, what those levels cost IN TOTAL, and how long that spend takes to earn
    itself back. The ``*_after`` fields describe the cheapest bumping level found;
    they are all None when no level up to the cap buys a tier (``reachable``
    False), which is why they are Optional rather than "unchanged".
    """

    skill: str
    building: str            # in-game display name, e.g. "Guild Brewery"
    from_level: int          # the guild's current building level (0..20)
    skill_levels_now: int    # levels the building grants today (+2 per level)
    tier_now: int
    points_now: int
    at_cap: bool             # True iff the building is already at level 20
    next_level_cost: Optional[int]   # gp for ONE more level (None at the cap)

    # --- the next-tier search ---------------------------------------------
    reachable: bool                  # True iff some level <= the cap buys a tier
    levels_needed: Optional[int]     # +1 steps to that tier (None: unreachable)
    to_level: Optional[int]          # from_level + levels_needed
    skill_levels_after: Optional[int]
    tier_after: Optional[int]
    points_after: Optional[int]
    points_gained: int               # 0 when unreachable
    total_cost: Optional[int]        # gp for ALL levels_needed steps together
    draws_to_return: Optional[float]  # draws of this skill to earn total_cost back
    weeks_to_return: Optional[float]  # ... in weeks, at 2.5 weeks between draws

    def to_dict(self) -> dict:
        return asdict(self)


def _cheapest_bumping_level(
    party: list[MemberRow],
    skill: str,
    target_scale: Optional[float],
    from_level: int,
    tier_now: int,
) -> Optional[tuple[int, TrialResult]]:
    """Lowest building level above ``from_level`` whose race clears a HIGHER tier.

    BINARY SEARCH, which is sound because the race is monotone in the building
    level: extra building levels can only raise the success delta in
    :func:`success` (nothing else in the race reads the building), so every tier is
    cleared no slower and ``tier_reached`` is non-decreasing in the level. That
    costs ~log2(20) ≈ 5 simulations per skill instead of up to 20 — and the
    assumption is pinned against a brute-force linear scan in
    ``tests/test_trials.py``.

    Returns ``(level, result)`` for the cheapest bumping level, or None when even
    the level-20 cap does not buy a tier for this party.
    """
    lo, hi = from_level + 1, config.GUILD_BUILDING_MAX_LEVEL
    found: Optional[tuple[int, TrialResult]] = None
    while lo <= hi:
        mid = (lo + hi) // 2
        result = simulate_race(
            party, skill, target_scale, building_skill_levels(mid)
        )
        if result.tier_reached > tier_now:
            found = (mid, result)
            hi = mid - 1     # a cheaper level may do just as well
        else:
            lo = mid + 1
    return found


def probe_building_upgrade(
    party: list[MemberRow],
    skill: str,
    target_scale: Optional[float] = None,
    current: Optional[TrialResult] = None,
) -> BuildingUpgrade:
    """How many levels of ``skill``'s guild building buy a tier, and do they pay?

    Searches upward from the guild's current building level for the CHEAPEST level
    that clears a higher tier inside the 1-hour budget (each level grants +2 skill
    levels to every member — see :func:`_cheapest_bumping_level`), then prices it:
    the cumulative guild-point cost of every step from the game's own cost curve,
    and how many draws / weeks that lump sum takes to earn back at +100 points per
    tier, once every ~2.5 weeks (:func:`upgrade_payback_weeks`).

    The party is held FIXED, which makes ``levels_needed`` — and therefore the cost
    and the payback — an UPPER BOUND: with a stronger building the optimizer might
    also reshuffle members between trials and reach the tier sooner. Re-optimising
    per candidate level would cost minutes of CI time for a speculative number, so
    it is deliberately not done.

    ``current`` may be passed to reuse an already-simulated result for the
    unupgraded case (identical inputs give an identical race, so this is purely
    to save the duplicate simulation).
    """
    from_level = guild_building_level(skill)
    at_cap = from_level >= config.GUILD_BUILDING_MAX_LEVEL

    now = (
        current
        if current is not None
        else simulate_race(party, skill, target_scale)
    )
    found = (
        None
        if at_cap
        else _cheapest_bumping_level(
            party, skill, target_scale, from_level, now.tier_reached
        )
    )

    # Fields that hold whether or not a bumping level exists.
    common = dict(
        skill=skill,
        building=config.GUILD_BUILDING_NAMES.get(skill, f"{skill} building"),
        from_level=from_level,
        skill_levels_now=building_skill_levels(from_level),
        tier_now=now.tier_reached,
        points_now=now.points,
        at_cap=at_cap,
        next_level_cost=(
            None if at_cap else guild_building_upgrade_cost(from_level + 1)
        ),
    )

    if found is None:
        return BuildingUpgrade(
            **common,
            reachable=False,
            levels_needed=None,
            to_level=None,
            skill_levels_after=None,
            tier_after=None,
            points_after=None,
            points_gained=0,
            total_cost=None,
            draws_to_return=None,
            weeks_to_return=None,
        )

    to_level, after = found
    total_cost = guild_building_upgrade_total_cost(from_level, to_level)
    gained = after.points - now.points
    return BuildingUpgrade(
        **common,
        reachable=True,
        levels_needed=to_level - from_level,
        to_level=to_level,
        skill_levels_after=building_skill_levels(to_level),
        tier_after=after.tier_reached,
        points_after=after.points,
        points_gained=gained,
        total_cost=total_cost,
        draws_to_return=upgrade_payback_draws(total_cost, gained),
        weeks_to_return=upgrade_payback_weeks(total_cost, gained),
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
    # Per drawn skill, the SKILL LEVELS the guild's building grants every member
    # (+2 per building level; 0 when that building is unbuilt). Recorded so the
    # page and trials.json state the assumption rather than hiding it.
    guild_building_levels: dict[str, int] = field(default_factory=dict)
    # One entry per drawn skill: how many levels of that skill's guild building
    # would buy this week's trial another tier, what those levels cost in total,
    # and how long the spend takes to earn itself back.
    building_upgrades: list[BuildingUpgrade] = field(default_factory=list)

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
            "guild_building_levels": self.guild_building_levels,
            "building_upgrades": [u.to_dict() for u in self.building_upgrades],
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
    # How many levels of each trial's guild building would buy another tier, and
    # when does that spend pay for itself? The parties above are held fixed, so
    # each answer is an upper bound on the cost (see probe_building_upgrade).
    upgrades = [
        probe_building_upgrade(
            assignment.parties[skill], skill, target_scale, current=result
        )
        for skill, result in zip(skills, trials)
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
        guild_building_levels={
            skill: guild_building_skill_levels(skill) for skill in skills
        },
        building_upgrades=upgrades,
    )
