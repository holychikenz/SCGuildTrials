"""Unit tests for the guild-trials model. No network access.

Covers equipment bonus resolution (including the Enhancing special cases and
the Bell-Farming-column = Alchemy mapping), success clamping, race-simulation
monotonicity and headcount penalty, deterministic assignment, and the points
formula. All member fixtures are built inline so nothing here touches Google
Sheets.
"""

import math

import pytest

from src import config
from src.reader import MemberRow, SkillEntry
from src import trials


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
# The member sheet's 10 skill columns (config.SKILLS): note "Bell Farming" is
# the 9th, and there is NO "Alchemy" column.
def _member(name, levels=None, checks=None):
    """Build a MemberRow.

    levels: {skill: level} (missing skills default to level 100).
    checks: {skill: (tool, top, bot)} (missing default to all False).
    """
    levels = levels or {}
    checks = checks or {}
    skills = {}
    for sk in config.SKILLS:
        tool, top, bot = checks.get(sk, (False, False, False))
        skills[sk] = SkillEntry(
            level=levels.get(sk, 100), tool=tool, top=top, bot=bot
        )
    return MemberRow(
        name=name, main_classes="", flex="", flex_levels=[], skills=skills
    )


# ---------------------------------------------------------------------------
# member_bonuses: baselines and checkboxes
# ---------------------------------------------------------------------------
def test_bonuses_baseline_no_checkboxes():
    m = _member("Base", {"Foraging": 120})
    b = trials.member_bonuses(m, "Foraging")

    assert b.level == 120
    # Holy tool (+7) speed + cape (+3) speed, no efficiency armour on top/bot.
    assert b.speed == pytest.approx(
        config.TOOL_SPEED_HOLY_PLUS7 + config.CAPE_SPEED_PLUS3
    )
    # Family piece efficiency + level-4 house (gathering: no production buff).
    assert b.efficiency == pytest.approx(
        config.ARMOUR_EFFICIENCY_PLUS7 + config.HOUSE_EFFICIENCY
    )
    assert b.success_bonus == 0.0


def test_bonuses_all_checkboxes_use_celestial_and_stack_armour():
    m = _member(
        "Geared", {"Foraging": 120}, {"Foraging": (True, True, True)}
    )
    b = trials.member_bonuses(m, "Foraging")

    # Celestial tool (checked) + cape speed.
    assert b.speed == pytest.approx(
        config.TOOL_SPEED_CELESTIAL_PLUS7 + config.CAPE_SPEED_PLUS3
    )
    # Family + top + bot efficiency all stack, plus the level-4 house
    # (Foraging is gathering, so no production efficiency buff).
    assert b.efficiency == pytest.approx(
        3 * config.ARMOUR_EFFICIENCY_PLUS7 + config.HOUSE_EFFICIENCY
    )
    assert b.success_bonus == 0.0


def test_enhancing_special_case_tool_is_success_gloves_are_speed():
    # Unchecked tool -> holy enhancer success; family gloves add speed.
    m = _member("Enh", {"Enhancing": 110})
    b = trials.member_bonuses(m, "Enhancing")

    assert b.success_bonus == pytest.approx(config.TOOL_SUCCESS_HOLY_PLUS7)
    # Speed = cape + enhancing gloves speed + community enhancing-speed buff +
    # the level-4 enhancing house (Observatory); NOT a tool speed term.
    assert b.speed == pytest.approx(
        config.CAPE_SPEED_PLUS3
        + config.GLOVES_ENHANCING_SPEED_PLUS7
        + config.COMMUNITY_ENHANCING_SPEED_BUFF
        + config.HOUSE_ENHANCING_SPEED
    )
    # No family-efficiency for enhancing (gloves went to speed); no top/bot;
    # the enhancing house grants speed, not efficiency.
    assert b.efficiency == pytest.approx(0.0)


def test_enhancing_celestial_tool_success():
    m = _member("Enh", {"Enhancing": 110}, {"Enhancing": (True, False, False)})
    b = trials.member_bonuses(m, "Enhancing")
    assert b.success_bonus == pytest.approx(config.TOOL_SUCCESS_CELESTIAL_PLUS7)


def test_trial_skill_to_sheet_column_mapping():
    # THE JOKE: Alchemy reads the "Bell Farming" column; everything else is
    # identity. There is no real "Bell Farming" trial.
    assert config.TRIAL_SKILL_TO_SHEET_COLUMN["Alchemy"] == "Bell Farming"
    for sk in ["Milking", "Foraging", "Woodcutting", "C.Smithing", "Crafting",
               "Tailoring", "Cooking", "Brewing", "Enhancing"]:
        assert config.TRIAL_SKILL_TO_SHEET_COLUMN[sk] == sk


def test_alchemy_reads_bell_farming_column_level_and_checks():
    # Alchemy pulls its level AND Tool/Top/Bot straight from "Bell Farming".
    m = _member(
        "Al", {"Bell Farming": 137}, {"Bell Farming": (True, True, False)}
    )
    b = trials.member_bonuses(m, "Alchemy")

    assert b.level == 137
    assert b.tool is True and b.top is True and b.bot is False
    # Non-enhancing: celestial tool speed (tool checked) + cape speed.
    assert b.speed == pytest.approx(
        config.TOOL_SPEED_CELESTIAL_PLUS7 + config.CAPE_SPEED_PLUS3
    )
    # Family piece + skilling top efficiency (bot unchecked), plus the level-4
    # house and the community production-efficiency buff (Alchemy = production).
    assert b.efficiency == pytest.approx(
        2 * config.ARMOUR_EFFICIENCY_PLUS7
        + config.HOUSE_EFFICIENCY
        + config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF
    )


def test_alchemy_is_not_a_mean_proxy():
    # The old model averaged known levels; the new model must read the column
    # verbatim. Set every other skill to 100 and Bell Farming to 50 so a mean
    # proxy (~95) would be clearly distinguishable from the real value (50).
    levels = {sk: 100 for sk in config.SKILLS}
    levels["Bell Farming"] = 50
    m = _member("Al", levels)
    assert trials.member_bonuses(m, "Alchemy").level == 50


def test_alchemy_rate_uses_bell_farming_column():
    # Alchemy's rate must equal a manual computation from the Bell Farming cell.
    m = _member(
        "Al", {"Bell Farming": 120}, {"Bell Farming": (False, False, False)}
    )
    b = trials.member_bonuses(m, "Alchemy")
    expected = (
        trials.success(120, 1, 0.0)
        * math.floor(120 * (1 + b.efficiency))
        / (config.ACTION_SECONDS_DEFAULT / (1 + b.speed))
    )
    assert trials.rate(m, "Alchemy", 1) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# success clamping
# ---------------------------------------------------------------------------
def test_success_floored_at_five_percent_at_large_negative_delta():
    # level 100 vs a very high tier -> raw success goes negative -> MAX(0.05,..).
    s = trials.success(level=100, tier=50, success_bonus=0.0)
    assert s == pytest.approx(config.SUCCESS_FLOOR)
    assert config.SUCCESS_FLOOR == 0.05


def test_success_clamped_to_one_at_large_positive_bonus():
    # Huge success bonus would exceed 1 -> clamp to 1.
    s = trials.success(level=200, tier=1, success_bonus=5.0)
    assert s == 1.0


def test_success_matches_formula_midrange():
    # level 120, tier 1 (tierLevel 100): delta +20 -> 0.8*(1+0.1) = 0.88.
    s = trials.success(level=120, tier=1, success_bonus=0.0)
    assert s == pytest.approx(0.8 * (1 + 20 * 0.005))


def test_building_skill_levels_added_to_effective_level(monkeypatch):
    # BuildingSkillLevels is added to the member's own level before comparing
    # to the difficulty level: level 90 + 10 building levels behaves like a bare
    # level 100 (both give effective level 100 -> delta 0 -> 0.8).
    baseline_100 = trials.success(100, 1, 0.0)  # default BUILDING_SKILL_LEVELS = 0
    monkeypatch.setattr(config, "BUILDING_SKILL_LEVELS", 10)
    assert trials.success(90, 1, 0.0) == pytest.approx(baseline_100)


# ---------------------------------------------------------------------------
# work target (TotalWork = DifficultyLevel * 400 * (1 + N/100))
# ---------------------------------------------------------------------------
def test_base_target_uses_400_coefficient():
    assert config.TIER_TARGET_PER_LEVEL == 400
    # DifficultyLevel(3) = 120 -> baseTarget = 120 * 400 = 48000.
    assert trials.base_target(3) == pytest.approx(trials.tier_level(3) * 400)


def test_total_work_headcount_term_and_neutral_scale():
    # TARGET_SCALE is pinned to 1.0; the 400 coefficient carries the scaling.
    assert config.TARGET_SCALE == 1.0
    # effectiveTarget(t=3, N=22) = 120 * 400 * (1 + 22/100).
    expected = trials.tier_level(3) * 400 * (1 + 22 / 100)
    got = trials.effective_target(3, party_size=22, target_scale=config.TARGET_SCALE)
    assert got == pytest.approx(expected)


# ---------------------------------------------------------------------------
# rate
# ---------------------------------------------------------------------------
def test_rate_matches_manual_computation():
    # Foraging is a gathering skill, so the lab-style doubling chance applies.
    m = _member("R", {"Foraging": 120})
    b = trials.member_bonuses(m, "Foraging")
    expected = (
        trials.success(120, 1, 0.0)
        * (1 + config.DOUBLE_CHANCE)
        * math.floor(120 * (1 + b.efficiency))
        / (config.ACTION_SECONDS_DEFAULT / (1 + b.speed))
    )
    assert trials.rate(m, "Foraging", 1) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# community buffs
# ---------------------------------------------------------------------------
def test_double_chance_gathering_only():
    # Gathering skills carry the +20% buff + ~5% gear; other families carry 0.
    for sk in ("Milking", "Foraging", "Woodcutting"):
        assert trials.double_chance(sk) == pytest.approx(config.DOUBLE_CHANCE)
    for sk in ("Alchemy", "Enhancing"):
        assert trials.double_chance(sk) == 0.0


def test_gathering_rate_scales_by_double_chance():
    # A gathering member's rate is exactly (1 + DOUBLE_CHANCE) of the same
    # computation without the doubling factor.
    m = _member("G", {"Woodcutting": 120})
    b = trials.member_bonuses(m, "Woodcutting")
    base = (
        trials.success(120, 1, 0.0)
        * math.floor(120 * (1 + b.efficiency))
        / (config.ACTION_SECONDS_DEFAULT / (1 + b.speed))
    )
    assert trials.rate(m, "Woodcutting", 1) == pytest.approx(
        base * (1 + config.DOUBLE_CHANCE)
    )


def test_production_efficiency_buff_applied():
    # Alchemy (production): efficiency includes the +0.15 community buff on top
    # of the +7 family piece, and no doubling chance.
    m = _member("P", {"Bell Farming": 120})
    b = trials.member_bonuses(m, "Alchemy")
    assert b.efficiency == pytest.approx(
        config.ARMOUR_EFFICIENCY_PLUS7
        + config.HOUSE_EFFICIENCY
        + config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF
    )
    assert trials.double_chance("Alchemy") == 0.0


def test_enhancing_speed_buff_applied():
    # Enhancing gains the +0.20 community speed buff (cape + gloves + buff),
    # and never the production efficiency buff.
    m = _member("E", {"Enhancing": 120})
    b = trials.member_bonuses(m, "Enhancing")
    assert b.speed == pytest.approx(
        config.CAPE_SPEED_PLUS3
        + config.GLOVES_ENHANCING_SPEED_PLUS7
        + config.COMMUNITY_ENHANCING_SPEED_BUFF
        + config.HOUSE_ENHANCING_SPEED
    )
    assert b.efficiency == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# per-member house level (sheet "H" column)
# ---------------------------------------------------------------------------
def test_blank_house_falls_back_to_default_level():
    # No "H" cell -> DEFAULT_HOUSE_LEVEL; equals the reference HOUSE_EFFICIENCY.
    m = _member("D", {"Foraging": 120})  # SkillEntry.house defaults to None
    b = trials.member_bonuses(m, "Foraging")
    assert b.efficiency == pytest.approx(
        config.ARMOUR_EFFICIENCY_PLUS7
        + config.HOUSE_EFFICIENCY_PER_LEVEL * config.DEFAULT_HOUSE_LEVEL
    )


def test_real_gathering_house_level_scales_efficiency():
    m = _member("H", {"Foraging": 120})
    m.skills["Foraging"].house = 7
    b = trials.member_bonuses(m, "Foraging")
    assert b.efficiency == pytest.approx(
        config.ARMOUR_EFFICIENCY_PLUS7 + config.HOUSE_EFFICIENCY_PER_LEVEL * 7
    )


def test_real_enhancing_house_level_scales_speed():
    m = _member("H", {"Enhancing": 120})
    m.skills["Enhancing"].house = 6
    b = trials.member_bonuses(m, "Enhancing")
    assert b.speed == pytest.approx(
        config.CAPE_SPEED_PLUS3
        + config.GLOVES_ENHANCING_SPEED_PLUS7
        + config.COMMUNITY_ENHANCING_SPEED_BUFF
        + config.HOUSE_ENHANCING_SPEED_PER_LEVEL * 6
    )


def test_house_level_clamped_to_max():
    m = _member("C", {"Foraging": 120})
    m.skills["Foraging"].house = 999  # absurd -> clamp to HOUSE_MAX_LEVEL
    b = trials.member_bonuses(m, "Foraging")
    assert b.efficiency == pytest.approx(
        config.ARMOUR_EFFICIENCY_PLUS7
        + config.HOUSE_EFFICIENCY_PER_LEVEL * config.HOUSE_MAX_LEVEL
    )


def test_missing_level_yields_zero_rate():
    m = _member("Z", {"Foraging": None})
    m.skills["Foraging"] = SkillEntry(level=None, tool=False, top=False, bot=False)
    assert trials.rate(m, "Foraging", 1) == 0.0


# ---------------------------------------------------------------------------
# simulate_race: monotonicity, headcount penalty, cap
# ---------------------------------------------------------------------------
def test_stronger_party_reaches_at_least_as_high_a_tier():
    weak = [_member(f"w{i}", {"Foraging": 100}) for i in range(10)]
    strong = [
        _member(f"s{i}", {"Foraging": 125}, {"Foraging": (True, True, True)})
        for i in range(10)
    ]
    tw = trials.simulate_race(weak, "Foraging").tier_reached
    ts = trials.simulate_race(strong, "Foraging").tier_reached
    assert ts >= tw


def test_adding_zero_rate_member_never_increases_tier():
    party = [_member(f"m{i}", {"Foraging": 120}) for i in range(10)]
    base = trials.simulate_race(party, "Foraging").tier_reached

    # A member with no usable level contributes 0 rate but still adds to N,
    # raising the effective target -> tier reached must not increase.
    dead_weight = _member("dead", {"Foraging": 0})
    dead_weight.skills["Foraging"] = SkillEntry(
        level=0, tool=False, top=False, bot=False
    )
    with_extra = trials.simulate_race(
        party + [dead_weight], "Foraging"
    ).tier_reached
    assert with_extra <= base


def test_headcount_penalty_raises_effective_target():
    small = trials.effective_target(5, party_size=10, target_scale=1.0)
    big = trials.effective_target(5, party_size=20, target_scale=1.0)
    assert big > small
    # Linear 1%/member: N=20 -> 1.20, N=10 -> 1.10.
    assert big / small == pytest.approx(1.20 / 1.10)


def test_party_of_21_forbidden_by_cap():
    members = [_member(f"m{i}", {"Foraging": 110}) for i in range(25)]
    asn = trials.random_assignment(
        members, ["Foraging", "Woodcutting"], seed=42, cap=20
    )
    assert all(len(p) <= 20 for p in asn.parties.values())


def test_empty_party_reaches_tier_zero_no_points():
    res = trials.simulate_race([], "Foraging")
    assert res.tier_reached == 0
    assert res.points == 0


# ---------------------------------------------------------------------------
# random_assignment: determinism
# ---------------------------------------------------------------------------
def test_assignment_deterministic_with_fixed_seed():
    members = [_member(f"m{i}", {"Foraging": 110}) for i in range(30)]
    skills = ["Foraging", "Woodcutting", "Alchemy", "Enhancing"]

    a1 = trials.random_assignment(members, skills, seed=42, cap=20)
    a2 = trials.random_assignment(members, skills, seed=42, cap=20)

    for sk in skills:
        assert [m.name for m in a1.parties[sk]] == [m.name for m in a2.parties[sk]]
    assert [m.name for m in a1.bench] == [m.name for m in a2.bench]


def test_assignment_bench_holds_overflow_and_no_duplicates():
    members = [_member(f"m{i}", {"Foraging": 110}) for i in range(86)]
    skills = ["Foraging", "Woodcutting", "Alchemy", "Enhancing"]
    asn = trials.random_assignment(members, skills, seed=42, cap=20)

    assigned = [m.name for p in asn.parties.values() for m in p]
    bench = [m.name for m in asn.bench]
    # 4 * 20 = 80 assigned, 6 benched, no member appears twice.
    assert len(assigned) == 80
    assert len(bench) == 6
    assert len(set(assigned + bench)) == 86


def test_different_seed_changes_assignment():
    members = [_member(f"m{i}", {"Foraging": 110}) for i in range(40)]
    skills = ["Foraging", "Woodcutting"]
    a1 = trials.random_assignment(members, skills, seed=1, cap=20)
    a2 = trials.random_assignment(members, skills, seed=2, cap=20)
    assert [m.name for m in a1.parties["Foraging"]] != [
        m.name for m in a2.parties["Foraging"]
    ]


# ---------------------------------------------------------------------------
# points formula
# ---------------------------------------------------------------------------
def test_points_formula():
    assert trials.points_for_tier(0) == 0
    assert trials.points_for_tier(1) == 200
    assert trials.points_for_tier(2) == 300
    assert trials.points_for_tier(11) == 1200
