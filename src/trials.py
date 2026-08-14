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
    workPower(m)        = level_m * (1 + efficiency_m + shrineEfficiency)  # own level
    actionSeconds(m)    = baseActionSeconds / (1 + speed_m + shrineSpeed)
    rate(m,t)           = success(m,t) * floor(workPower(m)) / actionSeconds(m)
    timeToClear(t)      = effectiveTarget(t,N) / sum_m rate(m,t)
    tier reached        = max T with sum_{t=1..T} timeToClear(t) <= 3600
    progress(T+1)       = (3600 - cumulative(T)) / timeToClear(T+1)
    creditTiers         = T + 0.5 * progress(T+1)
    points              = 100 + 100 * creditTiers

Enhancing is special: its tool grants SUCCESS (not speed), and its family
"gloves" grant SPEED (not efficiency); its base action time is 8s not 10s.

Two terms arrived with the 2026-08-11 game patch and both are load-bearing:

* ``creditTiers`` — a trial is now credited for PARTIAL progress into the tier it
  did not finish, at half rate. This is what stopped the objective being a step
  function, and much of :mod:`src.optimizer` was built on the assumption that it
  was one. See ``config.TRIAL_PARTIAL_CREDIT_RATE`` and
  ``research/partial-tier-credit.md``.
* ``shrineEfficiency`` / ``shrineSpeed`` — guild SHRINE buffs now apply inside
  trials. Guild-wide, not per-member, and only two of the five shrines reach the
  race at all. See :func:`guild_shrine_bonuses` and
  ``research/guild-shrines.md``.
"""

from __future__ import annotations

import contextlib
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
    # Guild-wide, NOT per-member: the SHRINE buffs, which since the 2026-08-11 patch
    # apply inside trials (Shrine of Force -> efficiency, Shrine of Tempo -> action
    # speed). SEPARATE FIELDS rather than folded into ``speed`` / ``efficiency``, and
    # deliberately so, for the same reason ``building_levels`` is separate from
    # ``level``: those two fields mean "what this MEMBER owns", and a guild-wide buff
    # is not that. It also keeps every bonus-assembly test honest — several assert the
    # member's own efficiency is exactly 0.0 for Enhancing, which is still true and
    # would silently stop being checkable if a guild buff were summed into it.
    # :func:`_prepare_member` adds them at the point of use.
    shrine_speed: float = 0.0
    shrine_efficiency: float = 0.0


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

    While the community gathering buff is live, gathering skills carry the buff
    plus ~+5% gear (config.DOUBLE_CHANCE); every other family carries 0. Scales
    work rate by ``(1 + double_chance)`` in :func:`rate`, per the lab-sim formula
    (research/trial-messages.md).
    """
    return config.DOUBLE_CHANCE if _is_gathering(skill) else 0.0


# ---------------------------------------------------------------------------
# Community buffs: the level ladder
# ---------------------------------------------------------------------------
def community_buff_value(family: str, level: int) -> float:
    """The community buff for ``family`` at ladder ``level`` (1..20).

    CONFIRMED game data: ``flatBoost + (level - 1) * flatBoostLevelBonus`` over
    ``config.COMMUNITY_BUFF_LADDER``. Note that ``flatBoost !=
    flatBoostLevelBonus`` for these buffs, so the ``per_level * level`` shortcut
    the buildings/houses/shrines use does NOT apply here — see the block comment
    in :mod:`src.config` and ``research/community-buffs.md``.

    ``level`` is clamped to 1..``config.COMMUNITY_BUFF_MAX_LEVEL`` — the ladder the
    game itself offers. Note what the low end therefore means: level 0 resolves to
    the level-1 value, NOT to zero, because level 1 is where the ladder starts and
    a buff below it does not exist rather than granting less. An *inactive* buff is
    a different question and a different shape — a regime, priced by
    ``calibrate.scenario_buffs_lapsed``, not a level.

    Rounded to 6dp purely so a level-20 value reads as ``0.197`` rather than
    ``0.19700000000000003`` in JSON and on the page.
    """
    base, per_level = config.COMMUNITY_BUFF_LADDER[family]
    level = _clamp(level, 1, config.COMMUNITY_BUFF_MAX_LEVEL)
    return round(base + (level - 1) * per_level, 6)


@contextlib.contextmanager
def community_buff_level(level: int):
    """Run a block with every modelled community buff set to ``level``.

    Rebinds the three magnitudes the rate model reads
    (``COMMUNITY_GATHERING_BUFF_DOUBLE``, ``COMMUNITY_PRODUCTION_EFFICIENCY_BUFF``,
    ``COMMUNITY_ENHANCING_SPEED_BUFF``), the composed ``DOUBLE_CHANCE``, and
    ``COMMUNITY_BUFF_LEVEL`` itself so that a ``WeekResult`` produced inside the
    block records the regime it actually ran under. All five are restored on the way
    out, exception or no.

    Rebinding module constants rather than threading a ``level`` parameter is
    deliberate, and follows the precedent ``calibrate.scenario_buffs_lapsed``
    already set: every function in the rate model reads ``config`` at CALL time,
    the buffs are common-mode across the whole party by definition, and a
    parameter would have to be carried through ``member_bonuses`` ->
    ``_prepare_member`` -> ``rate`` -> ``simulate_race`` -> the optimizer's hot
    loop to reach the place it is used. NOT thread-safe, and not intended to be:
    the build is single-threaded and runs one regime at a time.

    Used by ``build.build_guild`` to publish the level-20 counterfactual page
    beside the default level-1 one.
    """
    names = (
        "COMMUNITY_GATHERING_BUFF_DOUBLE",
        "COMMUNITY_PRODUCTION_EFFICIENCY_BUFF",
        "COMMUNITY_ENHANCING_SPEED_BUFF",
        "DOUBLE_CHANCE",
        "COMMUNITY_BUFF_LEVEL",
    )
    saved = {name: getattr(config, name) for name in names}
    gathering = community_buff_value("gathering", level)
    try:
        config.COMMUNITY_GATHERING_BUFF_DOUBLE = gathering
        config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF = community_buff_value(
            "production", level
        )
        config.COMMUNITY_ENHANCING_SPEED_BUFF = community_buff_value(
            "enhancing", level
        )
        config.DOUBLE_CHANCE = gathering + config.GEAR_DOUBLE_CHANCE
        config.COMMUNITY_BUFF_LEVEL = _clamp(
            level, 1, config.COMMUNITY_BUFF_MAX_LEVEL
        )
        yield
    finally:
        for name, value in saved.items():
            setattr(config, name, value)


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


def member_skill_level(member: MemberRow, skill: str) -> Optional[int]:
    """The member's own recorded level in ``skill`` (None when the sheet has no cell).

    The plain reading of the sheet, with no guild buffs of any kind folded in — which
    is what an ELIGIBILITY rule has to compare against. The game's per-trial minimum
    sign-up level (patch 2026-08-11) gates on the character's own skill level, not on
    the level a guild building lends them.
    """
    return _resolve_level_and_checks(member, skill)[0]


def meets_min_level(
    member: MemberRow, skill: str, min_level: Optional[int]
) -> bool:
    """Whether ``member`` may sign up for ``skill`` under a minimum-level rule.

    ``None`` (no minimum set) admits everyone, including a member with no recorded
    level — the constraint is the officers', and absence of it is not a licence to
    invent one. A member with no recorded level is EXCLUDED whenever a minimum is set,
    since an unknown level cannot be shown to meet it.
    """
    if min_level is None:
        return True
    level = member_skill_level(member, skill)
    return level is not None and level >= min_level


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


def guild_shrine_level(shrine: str) -> int:
    """The guild's level (0..20) for ``shrine``, clamped so a typo cannot inflate it."""
    level = config.GUILD_SHRINE_LEVELS.get(shrine) or 0
    return max(0, min(config.GUILD_SHRINE_MAX_LEVEL, level))


def guild_shrine_bonuses(
    levels: Optional[dict[str, int]] = None
) -> tuple[float, float]:
    """``(speed, efficiency)`` the guild's shrines grant EVERY member inside a trial.

    Guild-wide, not per-member — the same shape as
    :func:`guild_building_skill_levels`, and resolved once per race rather than once
    per member.

    Only two of the five shrines reach the tier race: Shrine of Force grants
    ``/buff_types/efficiency`` and Shrine of Tempo ``/buff_types/action_speed``, both
    at +0.005 per level. Shrine of Rarity and Shrine of Spirit buff LOOT (rare find,
    essence find) and Shrine of Scholar buffs XP (wisdom); none of the three changes
    how fast work gets done, so none may touch this function's return value. The
    dispatch is data-driven from ``config.GUILD_SHRINE_SKILLING_BUFFS``, whose third
    element is the model channel or ``None`` — so a shrine is modelled only if the
    config says which channel it feeds, and a future shrine cannot be silently
    ignored *or* silently misapplied.

    Returns ``(0.0, 0.0)`` when ``config.SHRINE_BUFFS_APPLY_IN_TRIALS`` is False,
    restoring the pre-patch race exactly.

    ``levels`` overrides the guild's actual shrine levels (used to price a
    hypothetical upgrade without mutating global state — see
    :func:`probe_shrine_upgrade`).
    """
    if not config.SHRINE_BUFFS_APPLY_IN_TRIALS:
        return 0.0, 0.0
    speed = 0.0
    efficiency = 0.0
    for shrine, (_buff, per_level, channel) in (
        config.GUILD_SHRINE_SKILLING_BUFFS.items()
    ):
        if channel is None:
            continue  # loot or XP: real, but not part of the tier race
        if levels is None:
            level = guild_shrine_level(shrine)
        else:
            level = max(
                0, min(config.GUILD_SHRINE_MAX_LEVEL, levels.get(shrine) or 0)
            )
        if channel == "speed":
            speed += per_level * level
        elif channel == "efficiency":
            efficiency += per_level * level
        else:  # pragma: no cover - guarded so a typo fails loudly
            raise ValueError(
                f"shrine {shrine!r} names an unknown model channel {channel!r}; "
                "expected 'speed', 'efficiency' or None"
            )
    return speed, efficiency


def guild_shrine_upgrade_cost(to_level: int) -> Optional[int]:
    """Guild points to raise a shrine TO ``to_level`` (one step); None past the cap."""
    return config.GUILD_SHRINE_POINT_COSTS.get(to_level)


def guild_shrine_upgrade_total_cost(
    from_level: int, to_level: int
) -> Optional[int]:
    """Cumulative guild points from ``from_level`` to ``to_level``, or None past the cap.

    Same contract as :func:`guild_building_upgrade_total_cost`: 0 for a no-op, None if
    any step in the range is unpriced, so a caller can never quote a truncated total.
    """
    if to_level <= from_level:
        return 0
    total = 0
    for level in range(from_level + 1, to_level + 1):
        step = guild_shrine_upgrade_cost(level)
        if step is None:
            return None
        total += step
    return total


def guild_building_upgrade_cost(to_level: int) -> Optional[int]:
    """Guild points to raise a skilling building TO ``to_level`` (one step).

    Straight from ``config.GUILD_BUILDING_POINT_COSTS`` (the game's
    ``guildPointCosts``), so upgrading from level L costs
    ``guild_building_upgrade_cost(L + 1)`` — 500 for an unbuilt building's first
    level. Returns None beyond the level-20 cap.
    """
    return config.GUILD_BUILDING_POINT_COSTS.get(to_level)


def member_bonuses(
    member: MemberRow,
    skill: str,
    building_levels: Optional[int] = None,
    shrine: Optional[tuple[float, float]] = None,
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

      - Guild SHRINES (guild-wide, not per-member): Shrine of Force grants
        efficiency and Shrine of Tempo action speed, +0.005 per level each, applied
        inside trials since the 2026-08-11 patch. Carried on ``shrine_speed`` /
        ``shrine_efficiency`` and added at the point of use in
        :func:`_prepare_member` — see :func:`guild_shrine_bonuses`.

    ``building_levels`` overrides the guild-building contribution (in granted
    SKILL levels, not building levels) instead of reading it from the config —
    used to price a hypothetical upgrade without mutating global state. None
    means "use the guild's actual building". ``shrine`` does the same for the
    resolved ``(speed, efficiency)`` shrine tuple; resolve it ONCE per race and pass
    it in, as :func:`simulate_race` does.
    """
    level, tool, top, bot, house = _resolve_level_and_checks(member, skill)
    house_level = _house_level(house)
    if building_levels is None:
        building_levels = guild_building_skill_levels(skill)
    if shrine is None:
        shrine = guild_shrine_bonuses()
    shrine_speed, shrine_efficiency = shrine

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
        shrine_speed=shrine_speed,
        shrine_efficiency=shrine_efficiency,
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
    member: MemberRow,
    skill: str,
    building_levels: int,
    shrine: Optional[tuple[float, float]] = None,
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
    b = member_bonuses(member, skill, building_levels, shrine)
    if not b.level or b.level <= 0:
        return None
    # The guild-wide shrine buffs are added HERE rather than inside the member's own
    # speed/efficiency, so that MemberBonuses keeps saying what the member owns. They
    # enter the two channels the race actually reads and nowhere else.
    return (
        b.level,
        b.success_bonus,
        b.building_levels,
        1 + double_chance(skill),
        math.floor(work_power(b.level, b.efficiency + b.shrine_efficiency)),
        action_seconds(skill, b.speed + b.shrine_speed),
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


def tier_clear_seconds(result: "TrialResult") -> Optional[float]:
    """Elapsed seconds at which the party finished its LAST completed tier.

    The cumulative time of the highest tier actually cleared — i.e. the clock
    reading when the recorded score was banked, out of
    ``config.TRIAL_TIME_BUDGET_SECONDS``. ``None`` when no tier was cleared at all
    (nothing was banked, so there is no time to report).

    This is the absolute form of :func:`time_slack_fraction`, which is the same
    number expressed as the fraction of the budget left over. Both are derived
    here so the page and the optimizer can never disagree about the margin.
    """
    if result.tier_reached < 1:
        return None
    for step in reversed(result.timeline):
        if step.cleared and step.cumulative_time is not None:
            return step.cumulative_time
    return None


def time_slack_fraction(result: "TrialResult") -> float:
    """How much of the 1-hour budget the party had left over, as a fraction.

    ``1 - cumulative_time(T) / TRIAL_TIME_BUDGET_SECONDS`` for the highest tier T
    actually cleared, i.e. the relative time margin by which the recorded tier was
    held. In ``[0, 1)``: near 1 for a party that cleared its tier almost
    instantly, near 0 for one that scraped in with seconds to spare.

    WHY THIS EXISTS: ``points`` is a STEP function of the tier, so two assignments
    that reach the same tiers score identically even when one clears its last tier
    with 560 seconds spare and the other with 100 (measured on the live SC roster,
    2026-07-31 — see research/risk-aware-objective.md). That margin is the only
    protection against the model being slightly wrong, a member not turning up, or
    a community buff lapsing, so the optimizer's final pass maximises it as a
    TIE-BREAK once the points are settled (:func:`src.optimizer._refine_slack`).

    Returns 0.0 when no tier was cleared at all — a party that scores nothing has
    no margin to protect, and must never look "safe" by virtue of an empty
    timeline.
    """
    seconds = tier_clear_seconds(result)
    if seconds is None:
        return 0.0
    return 1.0 - seconds / config.TRIAL_TIME_BUDGET_SECONDS


def _normal_cdf(z: float) -> float:
    """Standard normal CDF, via ``math.erf`` — no SciPy dependency in the build."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _variance_rate(prepared: list[tuple], tier: int) -> float:
    """Party work-VARIANCE per second at ``tier`` — the aleatoric term.

    Each action is ``X = W * S * (1 + D)`` with ``S ~ Bern(p)`` the success roll
    and ``D ~ Bern(delta)`` the doubling roll, independent, so

        E[X]   = W * p * (1 + delta)              (exactly the shipped rate model)
        E[X^2] = W^2 * p * (1 + 3*delta)          since E[(1+D)^2] = 1 + 3*delta
        Var[X] = W^2 * [ p(1+3d) - p^2 (1+d)^2 ]  (-> W^2 p(1-p) when d = 0)

    The action COUNT is deterministic — ``action_seconds`` is fixed, so a member
    performs exactly tau/a actions in time tau and only the payload is random —
    which is the textbook setting for the CLT, and why this is a variance RATE
    that adds across members exactly as the drift does.

    ``prepared`` carries ``double = 1 + delta``, hence ``(1 + 3*delta)`` as
    ``3*double - 2``.

    FLAGGED ASSUMPTION: efficiency contributes no variance — the capture in
    research/trial-messages.md shows the engine folding it deterministically into
    progressPerAction. If a later capture shows it behaving as an instant-repeat
    CHANCE, a compound-Poisson term belongs here.
    """
    total = 0.0
    for level, success_bonus, building, double, wp, asec in prepared:
        p = success(level, tier, success_bonus, building)
        total += wp * wp * (p * (3.0 * double - 2.0) - p * p * double * double) / asec
    return total


def clear_sigma(
    party: list[MemberRow],
    skill: str,
    tier: int,
    building_levels: Optional[int] = None,
) -> Optional[float]:
    """Aleatoric sd of ``ln(clear time)`` for banking ``tier`` — the dice alone.

    First passage to a work level ``Y`` under drift ``R`` and variance rate ``V``
    is inverse-Gaussian with mean ``Y/R`` and variance ``Y*V/R^3`` (the standard
    Wald result). Tiers are raced sequentially and are independent to first order,
    so the variances accumulate and

        sigma_T = sqrt( sum_{t<=T} Target(t) * V_t / R_t^3 ) / tau_T

    is the sd of the LOG clearing time — which is what the risk bridge needs,
    because a multiplicative rate shock is multiplicative on the clock too.

    DELIBERATELY NOT COMPUTED INSIDE :func:`simulate_race`. The optimizer calls
    that ~87k times per pipeline and this would ride the hot loop for no benefit;
    the probability is wanted for the handful of races that actually get rendered,
    so it is a separate call made once per shipped trial.

    Returns None when the party cannot move at all.

    VALIDATED against a direct action-level roll (src/simulate_trial.py): the
    formula reproduces the simulated sd to within 0.2% at the marginal tier, and
    tracks it across all thirteen tiers of the live Foraging lineup.
    """
    if tier < 1:
        return None
    if building_levels is None:
        building_levels = guild_building_skill_levels(skill)
    shrine = guild_shrine_bonuses()
    prepared = [
        p
        for p in (_prepare_member(m, skill, building_levels, shrine) for m in party)
        if p is not None
    ]
    if not prepared:
        return None

    n = len(party)
    cumulative = 0.0
    variance = 0.0
    for t in range(1, tier + 1):
        rate = sum(
            success(level, t, success_bonus, building) * double * wp / asec
            for level, success_bonus, building, double, wp, asec in prepared
        )
        if rate <= 0:
            return None
        target = effective_target(t, n, config.TARGET_SCALE)
        cumulative += target / rate
        variance += target * _variance_rate(prepared, t) / rate ** 3
    if cumulative <= 0:
        return None
    return math.sqrt(variance) / cumulative


def clear_probability(
    party: list[MemberRow],
    skill: str,
    result: "TrialResult",
    building_levels: Optional[int] = None,
) -> Optional[float]:
    """P(this lineup actually banks the tier it is credited with).

    ``Phi( -ln(1 - m) / sigma )`` where ``m`` is :func:`time_slack_fraction` and
    ``sigma`` combines the party's own aleatoric sigma (:func:`clear_sigma`) with
    ``config.RISK_SIGMA_SYSTEMATIC`` in quadrature. See that constant for what the
    systematic term covers, what it deliberately excludes, and how both were
    validated.

    The number is CONDITIONAL on the assigned party turning up — this tool advises
    where to go and when to switch, not whether to appear.

    Returns None when no tier was banked: a trial that scored nothing has no
    margin to hold, and must never be rendered as a probability of anything.
    """
    tier = result.tier_reached
    if tier < 1:
        return None
    sigma_dice = clear_sigma(party, skill, tier, building_levels)
    if sigma_dice is None:
        return None
    sigma = math.hypot(sigma_dice, config.RISK_SIGMA_SYSTEMATIC)
    if sigma <= 0:
        return 1.0
    margin = time_slack_fraction(result)
    # -ln(1 - m) is the log of the slowdown the party can absorb. Guard the log
    # against a margin of exactly 1 (an instantaneous clear), which cannot arise
    # from a real race but would otherwise divide by zero.
    return _normal_cdf(-math.log(max(1e-12, 1.0 - margin)) / sigma)


def _cumulative_tier_times(
    party: list[MemberRow],
    skill: str,
    max_tier: int,
    building_levels: Optional[int] = None,
) -> list[float]:
    """Cumulative seconds to clear tiers ``1..max_tier``, IGNORING the hour budget.

    The nominal clearing curve ``tau_1 < tau_2 < ...`` that every risk calculation in
    this module needs. :func:`simulate_race` stops at the first tier it cannot afford,
    which is correct for scoring but truncates exactly the upside a favourable shock
    would reach — so this races past the buzzer instead, for as many tiers as asked.

    Returns ``[]`` when the party cannot move at all.

    DEV/REPORTING ONLY, like :func:`clear_sigma`, and for the same reason: it is a
    second pass over the party and the optimizer calls the race ~87k times per
    pipeline. Both are wanted for the handful of races that get published.
    """
    if building_levels is None:
        building_levels = guild_building_skill_levels(skill)
    shrine = guild_shrine_bonuses()
    prepared = [
        p
        for p in (_prepare_member(m, skill, building_levels, shrine) for m in party)
        if p is not None
    ]
    if not prepared:
        return []

    n = len(party)
    cumulative = 0.0
    out: list[float] = []
    for tier in range(1, max(1, max_tier) + 1):
        party_rate = sum(
            success(level, tier, success_bonus, building) * double * wp / asec
            for level, success_bonus, building, double, wp, asec in prepared
        )
        if party_rate <= 0:
            break
        cumulative += effective_target(tier, n, config.TARGET_SCALE) / party_rate
        out.append(cumulative)
    return out


def _normal_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def expected_credit_points(
    party: list[MemberRow],
    skill: str,
    result: "TrialResult",
    building_levels: Optional[int] = None,
) -> Optional[float]:
    """E[guild points] for this lineup, under the calibrated multiplicative shock.

    The number officers should plan against, as opposed to the deterministic
    ``credit_points`` the model scores — which is what the party earns if every die
    falls at its expectation, and is therefore an OPTIMISTIC point estimate.

    WHY IT MATTERS HERE AND NOW. Partial-tier credit let the optimizer find better
    assignments by reaching for tiers it holds by seconds (measured live: three of eight
    trials at ``P(holds) ~ 0.51``). That is the right gamble — falling short lands on the
    tier below with ~99% partial credit, so the downside is shallow — but it means the
    deterministic figure over-claims. See ``config.RISK_EXPECTED_POINTS``.

    THE MODEL, which is the probability bridge run to its conclusion rather than a new
    one. The party's rate carries a multiplicative shock ``R*exp(eps)``,
    ``eps ~ N(0, sigma^2)``, with sigma the party's own Wald dice (:func:`clear_sigma`)
    and ``config.RISK_SIGMA_SYSTEMATIC`` in quadrature. A rate shock is exactly a clock
    shock, so every cumulative clearing time becomes ``tau_t * exp(-eps)`` and both the
    tier reached and the partial progress follow deterministically::

        T(eps) = max{ t : tau_t * exp(-eps) <= BUDGET }
        f(eps) = (BUDGET - tau_T e^-eps) / ((tau_{T+1} - tau_T) e^-eps)
        E[pts] = integral points(T(eps), f(eps)) * phi(eps/sigma)/sigma d eps

    Integrated on a normalised midpoint grid over ``+/- RISK_QUADRATURE_SPAN`` sigmas
    rather than by Gauss-Hermite: the shipped build is pure-Python (numpy is a dev-only
    extra) and a hard-coded Hermite table is a mistyping waiting to happen. The
    integrand is bounded, this runs four times per guild, and ``sigma -> 0`` reproduces
    the deterministic answer to within 1e-9 — asserted in the tests.

    Returns None when there is nothing to price: the party cannot move, or sigma cannot
    be derived. Note this is deliberately NOT the objective — optimising it would choose
    the same parties, because the gamble it prices survives its own test — so it never
    enters :class:`src.optimizer.AssignmentScorer`.
    """
    if not config.RISK_EXPECTED_POINTS:
        return None

    budget = config.TRIAL_TIME_BUDGET_SECONDS
    tier = max(1, result.tier_reached)
    sigma_dice = clear_sigma(party, skill, tier, building_levels)
    if sigma_dice is None:
        return None
    sigma = math.hypot(sigma_dice, config.RISK_SIGMA_SYSTEMATIC)

    taus = _cumulative_tier_times(
        party,
        skill,
        result.tier_reached + config.RISK_LOOKAHEAD_TIERS,
        building_levels,
    )
    if not taus:
        return None

    def points_at(shock: float) -> float:
        """Credit points if the party's whole clock is scaled by ``exp(-shock)``."""
        scale = math.exp(-shock)
        banked = 0
        for value in taus:
            if value * scale <= budget:
                banked += 1
            else:
                break
        if banked >= len(taus):
            # Ran off the top of the lookahead: no next tier to be part-way through.
            # Only reachable on a shock large enough to clear every tier priced, which
            # RISK_LOOKAHEAD_TIERS is sized to keep negligible.
            return points_for_credit(banked, credit_tiers(banked, 0.0))
        start = taus[banked - 1] * scale if banked >= 1 else 0.0
        span = taus[banked] * scale - start
        fraction = 0.0 if span <= 0 else _clamp((budget - start) / span, 0.0, 1.0)
        return points_for_credit(banked, credit_tiers(banked, fraction))

    if sigma <= 0:
        return points_at(0.0)

    nodes = max(3, config.RISK_QUADRATURE_NODES)
    span = config.RISK_QUADRATURE_SPAN * sigma
    step = 2.0 * span / nodes
    total = 0.0
    weight_sum = 0.0
    for i in range(nodes):
        shock = -span + step * (i + 0.5)   # midpoints, so no node sits on an endpoint
        weight = _normal_pdf(shock / sigma)
        weight_sum += weight
        total += weight * points_at(shock)
    # Normalise by the realised weights rather than by step/sigma, so the truncated
    # tails cannot bias the answer downward — the result is a proper weighted mean over
    # the range priced, and the mass outside +/-5 sigma is ~6e-7.
    return total / weight_sum if weight_sum > 0 else None


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
# Partial-tier credit (game patch 2026-08-11)
# ---------------------------------------------------------------------------
def tier_progress_fraction(result: "TrialResult") -> float:
    """How far into the first UNCLEARED tier the party got, as a fraction of it.

    In ``[0, 1)``. The patch credits this progress
    (``config.TRIAL_PARTIAL_CREDIT_RATE`` of a tier per unit), so it is the term that
    removed the objective's degeneracy — see that constant.

    COSTS NOTHING. :func:`simulate_race` already records the failed tier with its
    ``time_to_clear``, and :func:`tier_clear_seconds` already reports the clock at the
    last banked tier, so the fraction is
    ``(budget - banked_at) / time_to_clear(failed tier)`` — arithmetic on numbers the
    race has already produced. ``research/risk-aware-objective.md`` names exactly this:
    "the information needed for every model below is already in the return value and is
    being discarded by ``.points``".

    Returns 0.0 when nothing was in progress: the party could not move at all (the
    failed step carries ``time_to_clear is None``), or the race ran to ``_MAX_TIER``
    and there is no failed step to be part-way through.

    NB :func:`simulate_race` computes the same number inline, where ``cumulative`` and
    ``ttc`` are already in hand; this is the form for reading it back off a finished
    result (the pages, the sign-up planner, and the tests).
    """
    budget = config.TRIAL_TIME_BUDGET_SECONDS
    banked = tier_clear_seconds(result) or 0.0
    for step in result.timeline:
        if step.cleared:
            continue
        if step.time_to_clear is None or step.time_to_clear <= 0:
            return 0.0
        return _clamp((budget - banked) / step.time_to_clear, 0.0, 1.0)
    return 0.0


def credit_tiers(
    tier_reached: int,
    progress_fraction: float,
    rate: Optional[float] = None,
) -> float:
    """``tier_reached + rate * progress_fraction`` — the tier credit a trial earns.

    ``rate`` defaults to ``config.TRIAL_PARTIAL_CREDIT_RATE``; at 0.0 this is exactly
    ``float(tier_reached)`` and the whole partial-credit change vanishes (the one-line
    rollback).
    """
    if rate is None:
        rate = config.TRIAL_PARTIAL_CREDIT_RATE
    return tier_reached + rate * progress_fraction


def points_for_credit(tier_reached: int, credit: float) -> float:
    """Guild points for ``credit`` tiers of progress, having banked ``tier_reached``.

    The partial-credit generalisation of :func:`points_for_tier`, and equal to it
    exactly (as a float) when ``credit == tier_reached``.

    ``config.TRIAL_PARTIAL_CREDIT_BASE_ON_PARTIAL`` decides the one genuinely
    unconfirmed case: whether the flat ``TRIAL_POINTS_BASE`` is awarded to a party that
    has completed NO tier but made progress toward one. The default (False) withholds
    it, because the shipped schedule's ``points(0) == 0`` reads the base as a reward for
    completing a tier rather than for approaching one — see the constant.
    """
    if credit <= 0:
        return 0.0
    if tier_reached < 1 and not config.TRIAL_PARTIAL_CREDIT_BASE_ON_PARTIAL:
        return config.TRIAL_POINTS_PER_TIER * credit
    return config.TRIAL_POINTS_BASE + config.TRIAL_POINTS_PER_TIER * credit


def points_for_result(
    result: "TrialResult", rate: Optional[float] = None
) -> float:
    """Guild points for ``result`` INCLUDING partial-tier credit.

    ``== float(points_for_tier(result.tier_reached))`` exactly when ``rate`` (or
    ``config.TRIAL_PARTIAL_CREDIT_RATE``) is 0.0.
    """
    fraction = tier_progress_fraction(result)
    return points_for_credit(
        result.tier_reached, credit_tiers(result.tier_reached, fraction, rate)
    )


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
    # Fraction of THIS tier's work completed when the hour ran out. Set on the first
    # UNCLEARED tier only (the one the party was part-way through); None on every
    # cleared tier, which is by definition 100% done, and None when the party could
    # not move at all. This is the term the 2026-08-11 patch pays partial credit on.
    progress_fraction: Optional[float] = None


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
    # DELIBERATELY UNCHANGED by the 2026-08-11 patch: the integer, step-function award
    # for the tier actually banked (points_for_tier). Every page column, every JSON
    # consumer and every test that pins the confirmed schedule reads this. The
    # partial-credit score lives beside it in ``credit_points`` so that turning the
    # patch off is one config line and turning it on breaks nothing that was already
    # true.
    points: int
    roster: list[RosterEntry] = field(default_factory=list)
    timeline: list[TierStep] = field(default_factory=list)
    # How far into the first uncleared tier the party got, in [0, 1) — the same number
    # as tier_progress_fraction(self), computed inline by simulate_race where the
    # cumulative time and time-to-clear are already in hand.
    partial_fraction: float = 0.0
    # Guild points INCLUDING partial-tier credit: the objective the optimizer
    # maximises. Equal to float(points) exactly when
    # config.TRIAL_PARTIAL_CREDIT_RATE is 0.0.
    credit_points: float = 0.0
    # P(this tier actually holds), filled in by run_week for the SHIPPED races
    # only — see clear_probability for why simulate_race does not compute it.
    # None means "not computed" or "no tier banked"; the page renders both as "—".
    clear_probability: Optional[float] = None
    # E[credit_points] under the calibrated shock — the honest figure beside the
    # optimistic one. Filled in by run_week for the SHIPPED races only, for the same
    # reason as clear_probability. See expected_credit_points.
    expected_points: Optional[float] = None

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
    # Guild-wide shrine buffs, resolved ONCE for the whole race (they are a property of
    # the guild, not of a member or a tier) — the same treatment the guild-building
    # lookup gets, and for the same performance reason.
    shrine = guild_shrine_bonuses()
    timeline: list[TierStep] = []
    cumulative = 0.0
    tier_reached = 0
    partial_fraction = 0.0

    # Tier-independent per-member factors, computed once for the whole race.
    prepared = [
        p
        for p in (_prepare_member(m, skill, building_levels, shrine) for m in party)
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
        # Partial progress into the tier the buzzer interrupted, which the 2026-08-11
        # patch pays credit on. ``cumulative`` is still the time banked by the last
        # CLEARED tier at this point (it is only advanced below), so this is the share
        # of THIS tier's work the party completed in the time that was left. Computed
        # here rather than by walking the timeline afterwards because both terms are
        # already in hand — the optimizer runs this ~87k times per pipeline.
        progress = (
            None if cleared else _clamp((budget - cumulative) / ttc, 0.0, 1.0)
        )
        timeline.append(
            TierStep(
                tier=tier,
                tier_level=tier_level(tier),
                effective_target=eff_target,
                party_rate=party_rate,
                time_to_clear=ttc,
                cumulative_time=would_be,
                cleared=cleared,
                progress_fraction=progress,
            )
        )
        if not cleared:
            partial_fraction = progress or 0.0
            break
        cumulative = would_be
        tier_reached = tier
        tier += 1

    final_tier = tier_reached if tier_reached >= 1 else 1
    # One member_bonuses per member (it used to be called four times each), and
    # the two reported rates reuse the prepared factors.
    roster = []
    for m in party:
        b = member_bonuses(m, skill, building_levels, shrine)
        p = _prepare_member(m, skill, building_levels, shrine)
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
        partial_fraction=partial_fraction,
        credit_points=points_for_credit(
            tier_reached, credit_tiers(tier_reached, partial_fraction)
        ),
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
    cost: Optional[int], points_gained: float
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
    points_gained: float,
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


@dataclass
class MinLevelAdvice:
    """The per-trial minimum sign-up level that would reproduce the model's own party.

    The patch gave leaders and generals a per-trial minimum sign-up level. Read as a
    constraint it is a nuisance; read as a LEVER it is the thing this tool has never had.
    The model has always been able to say "these members should sit this one out", and an
    officer has never had any way to make that happen short of asking people not to tick
    a box. The minimum level is that mechanism, and this is the number to type into it.

    ``suggested`` is simply the lowest level actually seated by the optimizer, so setting
    it excludes exactly the members the model already declined to pick and nobody else.
    It is advice, not a recommendation to act: a minimum also bars members from
    volunteering in future weeks, and it cannot distinguish "too weak to help" from "too
    weak to help *this* week alongside these particular twenty-three".
    """

    skill: str
    current: Optional[int]        # what the officers have set, if anything
    suggested: Optional[int]      # lowest level in the model's own party
    party_size: int
    # How many of the FULL roster the suggestion would bar from this trial, and how many
    # of those the model had already benched. Where the two agree, the setting merely
    # formalises a decision already taken; where `would_exclude` exceeds
    # `already_benched`, it would bar members this week's model was happy to seat.
    would_exclude: int
    already_benched: int

    def to_dict(self) -> dict:
        return asdict(self)


def advise_min_level(
    members: list[MemberRow],
    party: list[MemberRow],
    skill: str,
    current: Optional[int] = None,
) -> MinLevelAdvice:
    """Derive the minimum sign-up level that reproduces ``party`` for ``skill``."""
    levels = [
        lv for lv in (member_skill_level(m, skill) for m in party) if lv is not None
    ]
    suggested = min(levels) if levels else None
    seated = {id(m) for m in party}
    would_exclude = 0
    already_benched = 0
    if suggested is not None:
        for m in members:
            level = member_skill_level(m, skill)
            if level is not None and level >= suggested:
                continue
            would_exclude += 1
            if id(m) not in seated:
                already_benched += 1
    return MinLevelAdvice(
        skill=skill,
        current=current,
        suggested=suggested,
        party_size=len(party),
        would_exclude=would_exclude,
        already_benched=already_benched,
    )


@dataclass
class ShrineUpgrade:
    """What one more level of a guild shrine buys across the WHOLE week's draw.

    Deliberately shaped differently from :class:`BuildingUpgrade`, because a shrine is
    a different kind of purchase and pricing it the same way understates it by roughly
    an order of magnitude:

    * a BUILDING buffs one skill, so it pays only in the weeks that skill is drawn —
      ``TRIAL_WEEKS_BETWEEN_DRAWS`` (2.5) weeks apart on average;
    * a SHRINE buffs efficiency or action speed for everyone in every skill, so it pays
      in **all four trials, every week**.

    So the gain is summed across the drawn trials and the payback is quoted in weeks
    with no draw-frequency discount. An earlier draft of the plan priced shrines
    per-trial and per-2.5-weeks, which made them look about eight times worse than they
    are. They are still a poor buy — see the fields — but they deserve the honest
    number.

    ``points_gained`` is in CREDIT points, which is the only currency in which this
    question has an answer at all: before partial-tier credit, one shrine level almost
    never crossed a tier boundary anywhere, so the gain was exactly zero in every
    trial and the upgrade was unpriceable.
    """

    shrine: str              # config key, e.g. "force"
    name: str                # in-game display name, e.g. "Shrine of Force"
    buff: str                # in-game buff type, e.g. "efficiency"
    from_level: int
    at_cap: bool
    next_level_cost: Optional[int]     # gp for ONE more level (None at the cap)
    speed_now: float                   # this shrine's own contribution today
    efficiency_now: float
    credit_points_now: float           # week total, at today's shrine levels
    credit_points_after: Optional[float]   # week total with one more level
    points_gained: float               # summed across the week's drawn trials
    weeks_to_return: Optional[float]   # cost / gain — every week, not every 2.5

    def to_dict(self) -> dict:
        return asdict(self)


def probe_shrine_upgrade(
    parties: dict[str, list[MemberRow]],
    skills: list[str],
    shrine: str,
    target_scale: Optional[float] = None,
) -> ShrineUpgrade:
    """Price one more level of ``shrine`` against the whole week's drawn trials.

    The parties are held FIXED, exactly as :func:`probe_building_upgrade` holds them,
    so the gain is a LOWER bound on the benefit (a stronger buff might also let the
    optimizer reshuffle) and the payback an upper bound on the wait.

    Returns a zero-gain entry for a shrine that does not feed the race at all
    (Rarity/Spirit/Scholar), so the page can show that it was considered and priced at
    nothing rather than leaving the reader to wonder.
    """
    if target_scale is None:
        target_scale = config.TARGET_SCALE

    buff, per_level, channel = config.GUILD_SHRINE_SKILLING_BUFFS.get(
        shrine, ("unknown", 0.0, None)
    )
    from_level = guild_shrine_level(shrine)
    at_cap = from_level >= config.GUILD_SHRINE_MAX_LEVEL
    speed_now, efficiency_now = (
        (per_level * from_level, 0.0) if channel == "speed"
        else (0.0, per_level * from_level) if channel == "efficiency"
        else (0.0, 0.0)
    )

    def week_total(levels: Optional[dict[str, int]]) -> float:
        # simulate_race resolves the shrine itself, so the hypothetical is applied by
        # temporarily overriding the level map — the same trick probe_building_upgrade
        # avoids by threading an override, but here the buff is guild-wide rather than
        # per-skill and threading it would touch every call site for a dev-only number.
        if levels is None:
            return sum(
                simulate_race(parties[s], s, target_scale).credit_points
                for s in skills
            )
        saved = config.GUILD_SHRINE_LEVELS
        try:
            config.GUILD_SHRINE_LEVELS = {**saved, **levels}
            return sum(
                simulate_race(parties[s], s, target_scale).credit_points
                for s in skills
            )
        finally:
            config.GUILD_SHRINE_LEVELS = saved

    now = week_total(None)
    after: Optional[float] = None
    gained = 0.0
    cost = None if at_cap else guild_shrine_upgrade_cost(from_level + 1)
    if channel is not None and not at_cap:
        after = week_total({shrine: from_level + 1})
        gained = after - now

    return ShrineUpgrade(
        shrine=shrine,
        name=config.GUILD_SHRINE_NAMES.get(shrine, shrine.title()),
        buff=buff,
        from_level=from_level,
        at_cap=at_cap,
        next_level_cost=cost,
        speed_now=speed_now,
        efficiency_now=efficiency_now,
        credit_points_now=now,
        credit_points_after=after,
        points_gained=gained,
        # weeks_between_draws=1.0: a shrine pays every week, in every trial.
        weeks_to_return=upgrade_payback_weeks(cost, gained, 1.0),
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
    # Total INCLUDING partial-tier credit — the quantity the optimizer maximised.
    # Equals float(total_points) when config.TRIAL_PARTIAL_CREDIT_RATE is 0.0.
    total_credit_points: float = 0.0
    # Sum of the per-trial expectations. The gap to total_credit_points is what the
    # deterministic score over-claims, and it is the number to quote when the margins
    # are thin — see trials.expected_credit_points.
    total_expected_points: Optional[float] = None
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
    # The guild's shrine levels, and the (speed, efficiency) they grant every member in
    # every trial since the 2026-08-11 patch. Recorded so the page states the
    # assumption rather than hiding it, exactly as guild_building_levels does.
    guild_shrine_levels: dict[str, int] = field(default_factory=dict)
    shrine_speed: float = 0.0
    shrine_efficiency: float = 0.0
    # One entry per shrine: what ONE more level buys across the whole week, and how
    # long that spend takes to pay for itself. Unlike the buildings, a shrine pays in
    # every trial every week — see ShrineUpgrade.
    shrine_upgrades: list[ShrineUpgrade] = field(default_factory=list)
    # Per-trial minimum sign-up level: what the officers have set, and what would
    # reproduce the model's own party. The lever that turns the model's bench into
    # something the game will enforce — see MinLevelAdvice.
    min_levels: dict[str, Optional[int]] = field(default_factory=dict)
    min_level_advice: list[MinLevelAdvice] = field(default_factory=list)
    # The community-buff REGIME this week was simulated under: the ladder level and
    # the three magnitudes it resolves to. Recorded for the same reason
    # guild_shrine_levels is — the page and trials.json state the assumption instead
    # of hiding it — and because the trials page publishes TWO runs (the default
    # level and the level-20 counterfactual), so a reader holding one JSON file must
    # be able to tell which regime produced it. See config.COMMUNITY_BUFF_LADDER.
    community_buff_level: int = 0
    community_buff_gathering: float = 0.0
    community_buff_production: float = 0.0
    community_buff_enhancing: float = 0.0

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
            "total_credit_points": self.total_credit_points,
            "total_expected_points": self.total_expected_points,
            "strategy": self.strategy,
            "trials": [t.to_dict() for t in self.trials],
            "bench": self.bench,
            "guild_building_levels": self.guild_building_levels,
            "building_upgrades": [u.to_dict() for u in self.building_upgrades],
            "guild_shrine_levels": self.guild_shrine_levels,
            "shrine_speed": self.shrine_speed,
            "shrine_efficiency": self.shrine_efficiency,
            "shrine_upgrades": [u.to_dict() for u in self.shrine_upgrades],
            "min_levels": self.min_levels,
            "min_level_advice": [a.to_dict() for a in self.min_level_advice],
            "community_buff_level": self.community_buff_level,
            "community_buff_gathering": self.community_buff_gathering,
            "community_buff_production": self.community_buff_production,
            "community_buff_enhancing": self.community_buff_enhancing,
        }


def _week_defaults(
    skills: Optional[list[str]],
    seed: Optional[int],
    cap: Optional[int],
    target_scale: Optional[float],
    strategy: Optional[str],
    min_levels: Optional[dict[str, Optional[int]]],
) -> tuple[list[str], int, int, float, str, dict[str, Optional[int]]]:
    """Resolve the six ``run_week`` knobs against ``config``. Shared, so the
    assignment half and the scoring half can never disagree about a default."""
    return (
        list(skills if skills is not None else config.TRIAL_SKILLS_CURRENT),
        seed if seed is not None else config.TRIAL_RNG_SEED,
        cap if cap is not None else config.TRIAL_PARTY_CAP,
        config.TARGET_SCALE if target_scale is None else target_scale,
        config.TRIAL_OPTIMIZER_STRATEGY if strategy is None else strategy,
        dict(min_levels or {}),
    )


def choose_assignment(
    members: list[MemberRow],
    skills: Optional[list[str]] = None,
    seed: Optional[int] = None,
    cap: Optional[int] = None,
    target_scale: Optional[float] = None,
    strategy: Optional[str] = None,
    min_levels: Optional[dict[str, Optional[int]]] = None,
) -> Assignment:
    """Choose who races in which trial. THE EXPENSIVE HALF: 56-95s per guild.

    Split out from :func:`run_week` so the *cheap* half (:func:`score_assignment`,
    ~2ms) can be run repeatedly against ONE set of parties — which is what the
    trials page's community-buff selector is: one search, twenty ratings. See
    :func:`run_week_ladder`.

    ``strategy`` selects the Phase 2 assignment algorithm (see
    :mod:`src.optimizer`); ``"random"`` restores the Phase 1 shuffle. Defaults to
    ``config.TRIAL_OPTIMIZER_STRATEGY``. The optimizer is imported lazily to keep
    the ``trials`` <-> ``optimizer`` dependency one-directional at import time.
    """
    skills, seed, cap, target_scale, strategy, min_levels = _week_defaults(
        skills, seed, cap, target_scale, strategy, min_levels
    )
    if strategy == "random":
        assignment = random_assignment(members, skills, seed, cap)
        # The Phase-1 control strategy does no eligibility filtering of its own, so
        # apply the game's hard constraint here rather than publishing a party the
        # guild could not field.
        if any(v is not None for v in min_levels.values()):
            for skill in skills:
                limit = min_levels.get(skill)
                assignment.parties[skill] = [
                    m for m in assignment.parties[skill]
                    if meets_min_level(m, skill, limit)
                ]
        return assignment

    from .optimizer import optimize

    return optimize(
        members,
        skills,
        seed=config.TRIAL_OPTIMIZER_SEED,
        cap=cap,
        target_scale=target_scale,
        strategy=strategy,
        min_levels=min_levels,
    )


def score_assignment(
    assignment: Assignment,
    members: list[MemberRow],
    skills: Optional[list[str]] = None,
    seed: Optional[int] = None,
    cap: Optional[int] = None,
    target_scale: Optional[float] = None,
    strategy: Optional[str] = None,
    min_levels: Optional[dict[str, Optional[int]]] = None,
    now: Optional[datetime] = None,
) -> WeekResult:
    """Rate a FIXED set of parties. THE CHEAP HALF: ~2ms for the whole week.

    Every number the page prints, for parties somebody else has already chosen.
    :func:`simulate_race` is deterministic closed-form arithmetic and the two risk
    figures are quadrature, not sampling, so this is ~0.15ms per party and is safe
    to run twenty times over — once per rung of ``config.COMMUNITY_BUFF_LADDER``.

    ``now`` pins ``generated_at``/``week_date`` so a whole ladder of results can
    carry ONE timestamp: they describe one build, not twenty.

    NOTE the seam this exposes. Re-scoring fixed parties under a different regime
    answers "what would THIS plan score there", which is a LOWER BOUND on "what is
    the best plan there" — the optimiser would seat different members. That is the
    same fixed-party bound :func:`probe_building_upgrade` and
    :func:`probe_shrine_upgrade` already publish, and it must be labelled the same
    way wherever it is shown.
    """
    skills, seed, cap, target_scale, strategy, min_levels = _week_defaults(
        skills, seed, cap, target_scale, strategy, min_levels
    )
    trials = [
        simulate_race(assignment.parties[skill], skill, target_scale)
        for skill in skills
    ]
    # Attach the risk number ONCE per shipped race. The optimizer has finished by
    # now, so this is four calls rather than the ~87k the hot loop makes.
    for skill, result in zip(skills, trials):
        result.clear_probability = clear_probability(
            assignment.parties[skill], skill, result
        )
        # And the expectation the deterministic score understates. Same cost profile as
        # the probability: a couple of extra passes over four parties, long after the
        # optimizer has finished.
        result.expected_points = expected_credit_points(
            assignment.parties[skill], skill, result
        )
    # How many levels of each trial's guild building would buy another tier, and
    # when does that spend pay for itself? The parties above are held fixed, so
    # each answer is an upper bound on the cost (see probe_building_upgrade).
    upgrades = [
        probe_building_upgrade(
            assignment.parties[skill], skill, target_scale, current=result
        )
        for skill, result in zip(skills, trials)
    ]
    # What the shrines grant today, and what one more level of each would buy across
    # the whole week. Cheap: five shrines x four races, well outside the hot loop.
    shrine_speed, shrine_efficiency = guild_shrine_bonuses()
    shrine_upgrades = [
        probe_shrine_upgrade(assignment.parties, skills, shrine, target_scale)
        for shrine in config.GUILD_SHRINE_SKILLING_BUFFS
    ]
    now = datetime.now(timezone.utc) if now is None else now
    return WeekResult(
        generated_at=now.isoformat(),
        week_date=now.strftime("%Y-%m-%d"),
        skills=skills,
        seed=seed,
        cap=cap,
        target_scale=target_scale,
        member_count=len(members),
        total_points=sum(t.points for t in trials),
        total_credit_points=sum(t.credit_points for t in trials),
        total_expected_points=(
            sum(t.expected_points for t in trials)
            if all(t.expected_points is not None for t in trials)
            else None
        ),
        strategy=strategy,
        trials=trials,
        bench=[m.name for m in assignment.bench],
        guild_building_levels={
            skill: guild_building_skill_levels(skill) for skill in skills
        },
        building_upgrades=upgrades,
        guild_shrine_levels={
            shrine: guild_shrine_level(shrine)
            for shrine in config.GUILD_SHRINE_SKILLING_BUFFS
        },
        shrine_speed=shrine_speed,
        shrine_efficiency=shrine_efficiency,
        shrine_upgrades=shrine_upgrades,
        min_levels=min_levels,
        min_level_advice=[
            advise_min_level(
                members, assignment.parties[skill], skill, min_levels.get(skill)
            )
            for skill in skills
        ],
        # Read from config LIVE rather than recomputed from the ladder, so the
        # figures recorded are exactly the ones the simulation above ran on —
        # including inside community_buff_level() and calibrate's lapsed scenario.
        community_buff_level=config.COMMUNITY_BUFF_LEVEL,
        community_buff_gathering=config.COMMUNITY_GATHERING_BUFF_DOUBLE,
        community_buff_production=config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF,
        community_buff_enhancing=config.COMMUNITY_ENHANCING_SPEED_BUFF,
    )


def run_week(
    members: list[MemberRow],
    skills: Optional[list[str]] = None,
    seed: Optional[int] = None,
    cap: Optional[int] = None,
    target_scale: Optional[float] = None,
    strategy: Optional[str] = None,
    min_levels: Optional[dict[str, Optional[int]]] = None,
) -> WeekResult:
    """Assign parties and simulate all of this week's skilling trials.

    Unchanged in behaviour: :func:`choose_assignment` followed by
    :func:`score_assignment`, which is exactly what this function's body used to be
    in one piece.
    """
    assignment = choose_assignment(
        members, skills, seed, cap, target_scale, strategy, min_levels
    )
    return score_assignment(
        assignment, members, skills, seed, cap, target_scale, strategy, min_levels
    )


def run_week_ladder(
    members: list[MemberRow],
    skills: Optional[list[str]] = None,
    seed: Optional[int] = None,
    cap: Optional[int] = None,
    target_scale: Optional[float] = None,
    strategy: Optional[str] = None,
    min_levels: Optional[dict[str, Optional[int]]] = None,
    levels: Optional[list[int]] = None,
) -> tuple[WeekResult, dict[int, WeekResult]]:
    """ONE optimiser run, then that same plan rated at every community-buff level.

    Returns ``(published, ladder)``: the week as ``run_week`` would have produced
    it under the ambient ``config.COMMUNITY_BUFF_LEVEL``, and a ``{level:
    WeekResult}`` map over ``levels`` (default the game's whole 1..20 ladder). Every
    entry seats the SAME members in the SAME trials — only the rates, tiers, margins
    and points move.

    WHY THIS SHAPE, AND WHAT IT IS NOT. Re-optimising per level would cost ~85s a
    rung, ~30 minutes a guild; re-rating costs ~2ms a rung, so the whole ladder is
    free beside the one search that produced it. The price of that bargain is stated
    in :func:`score_assignment`: each rung is a LOWER BOUND on what the guild could
    score at that level, because the optimiser would seat different members. The
    page carrying these numbers must say so.

    The published entry is *also* in the ladder (at its own level) and is the same
    object, so the selector's default rung and the page it sits on can never drift
    apart. Every rung shares one ``generated_at``: they describe one build.
    """
    if levels is None:
        levels = list(range(1, config.COMMUNITY_BUFF_MAX_LEVEL + 1))
    assignment = choose_assignment(
        members, skills, seed, cap, target_scale, strategy, min_levels
    )
    now = datetime.now(timezone.utc)
    args = (assignment, members, skills, seed, cap, target_scale, strategy, min_levels)
    published = score_assignment(*args, now=now)
    ladder: dict[int, WeekResult] = {published.community_buff_level: published}
    for level in levels:
        if level in ladder:
            continue
        # community_buff_level rebinds config globals and restores them on the way
        # out, so each rung is scored in isolation and the ambient regime survives
        # the loop. NB: never hand an optimizer.AssignmentScorer across this
        # boundary — its cache is keyed on the party alone and is regime-blind.
        with community_buff_level(level):
            ladder[level] = score_assignment(*args, now=now)
    return published, dict(sorted(ladder.items()))
