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


def test_building_skill_levels_added_to_effective_level():
    # BuildingSkillLevels is added to the member's own level before comparing
    # to the difficulty level: level 90 + 10 building levels behaves like a bare
    # level 100 (both give effective level 100 -> delta 0 -> 0.8).
    baseline_100 = trials.success(100, 1, 0.0)  # no building term by default
    assert trials.success(90, 1, 0.0, building_levels=10) == pytest.approx(
        baseline_100
    )


# ---------------------------------------------------------------------------
# guild buildings (guild-wide +2 skill levels per building level)
# ---------------------------------------------------------------------------
def test_guild_building_levels_all_zero_in_shipped_config():
    # Live data (guild_updated capture 2026-07-22): no skilling guild building is
    # built, so the model must add nothing today.
    for skill in config.GUILD_BUILDING_LEVELS:
        assert trials.guild_building_skill_levels(skill) == 0


def test_guild_building_grants_two_levels_per_building_level(monkeypatch):
    monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, "Brewing", 7)
    # +2 per building level: a level-7 Guild Brewery is worth +14 brewing levels.
    assert trials.guild_building_skill_levels("Brewing") == 14
    # ...and only that skill: its neighbours are untouched.
    assert trials.guild_building_skill_levels("Cooking") == 0


def test_guild_building_level_clamped_to_max(monkeypatch):
    monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, "Brewing", 999)
    assert trials.guild_building_skill_levels("Brewing") == (
        config.GUILD_BUILDING_SKILL_LEVELS_PER_LEVEL * config.GUILD_BUILDING_MAX_LEVEL
    )


def test_guild_building_unknown_or_none_skill_grants_nothing(monkeypatch):
    assert trials.guild_building_skill_levels("Bell Farming") == 0  # not a trial skill
    monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, "Brewing", None)
    assert trials.guild_building_skill_levels("Brewing") == 0


def test_member_bonuses_carries_guild_building_levels(monkeypatch):
    monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, "Brewing", 10)
    m = _member("B", {"Brewing": 100, "Cooking": 100})
    assert trials.member_bonuses(m, "Brewing").building_levels == 20
    assert trials.member_bonuses(m, "Cooking").building_levels == 0


def test_guild_building_raises_rate_via_success_only(monkeypatch):
    # A level-10 Guild Brewery (+20 levels) must raise the success term and
    # nothing else: work power and action time are unchanged, so the rate rises
    # by exactly the success ratio.
    m = _member("B", {"Brewing": 100})
    before = trials.rate(m, "Brewing", 1)
    monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, "Brewing", 10)
    after = trials.rate(m, "Brewing", 1)
    expected_ratio = trials.success(100, 1, 0.0, 20) / trials.success(100, 1, 0.0)
    assert after == pytest.approx(before * expected_ratio)
    assert after > before


def test_guild_building_does_not_change_work_power(monkeypatch):
    # UNCONFIRMED in game data, so deliberately excluded: work power reads the
    # member's own sheet level only.
    m = _member("B", {"Brewing": 100})
    b_before = trials.member_bonuses(m, "Brewing")
    monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, "Brewing", 20)
    b_after = trials.member_bonuses(m, "Brewing")
    assert trials.work_power(b_after.level, b_after.efficiency) == pytest.approx(
        trials.work_power(b_before.level, b_before.efficiency)
    )


def test_guild_building_can_lift_the_tier_reached(monkeypatch):
    # The point of the whole exercise: more effective level -> higher success at
    # the hard tiers -> a better tier within the same 1-hour budget.
    party = [_member(f"M{i}", {"Brewing": 110}) for i in range(10)]
    before = trials.simulate_race(party, "Brewing")
    monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, "Brewing", 20)  # +40 levels
    after = trials.simulate_race(party, "Brewing")
    assert after.tier_reached > before.tier_reached
    assert after.points > before.points


def test_run_week_records_guild_building_levels():
    # The assumption is published, not hidden: trials.json carries the granted
    # levels for every drawn skill.
    members = [_member(f"M{i}", {sk: 110 for sk in config.SKILLS}) for i in range(8)]
    wk = trials.run_week(members, skills=["Brewing", "Milking"], strategy="random")
    assert wk.to_dict()["guild_building_levels"] == {"Brewing": 0, "Milking": 0}


# ---------------------------------------------------------------------------
# guild-building upgrade probe ("how many levels buy a tier, and do they pay?")
# ---------------------------------------------------------------------------
def test_building_level_and_granted_levels_are_distinct_and_clamped(monkeypatch):
    monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, "Brewing", 3)
    assert trials.guild_building_level("Brewing") == 3         # building level
    assert trials.guild_building_skill_levels("Brewing") == 6  # granted levels
    assert trials.building_skill_levels(0) == 0
    assert trials.building_skill_levels(999) == 40             # clamped at L20


def test_upgrade_cost_comes_from_the_game_cost_curve():
    # guildPointCosts: an unbuilt building's first level is 500; the cap is 20.
    assert trials.guild_building_upgrade_cost(1) == 500
    assert trials.guild_building_upgrade_cost(2) == 675
    assert trials.guild_building_upgrade_cost(20) == 149725
    assert trials.guild_building_upgrade_cost(21) is None


def test_simulate_race_override_does_not_touch_config():
    # The probe must price a hypothetical without mutating global state.
    party = [_member(f"M{i}", {"Brewing": 113}) for i in range(10)]
    before = trials.simulate_race(party, "Brewing").tier_reached
    hypothetical = trials.simulate_race(
        party, "Brewing", None, trials.building_skill_levels(1)
    ).tier_reached
    assert hypothetical > before
    assert config.GUILD_BUILDING_LEVELS["Brewing"] == 0        # untouched
    assert trials.simulate_race(party, "Brewing").tier_reached == before


def test_total_upgrade_cost_sums_every_step():
    # The game prices each LEVEL, so a multi-level upgrade is the sum of the steps.
    assert trials.guild_building_upgrade_total_cost(0, 3) == 500 + 675 + 900
    assert trials.guild_building_upgrade_total_cost(6, 7) == 3025  # single step
    assert trials.guild_building_upgrade_total_cost(4, 4) == 0     # no-op
    assert trials.guild_building_upgrade_total_cost(9, 4) == 0     # backwards
    # A range running past the cap is unpriceable, NOT silently truncated.
    assert trials.guild_building_upgrade_total_cost(18, 21) is None


def test_payback_converts_a_lump_sum_into_draws_and_weeks():
    # 500 gp buying +100 points a draw repays in 5 draws; a skill is drawn every
    # 2.5 weeks (four of ten per week), so 12.5 weeks.
    assert config.TRIAL_WEEKS_BETWEEN_DRAWS == 2.5
    assert trials.upgrade_payback_draws(500, 100) == 5.0
    assert trials.upgrade_payback_weeks(500, 100) == pytest.approx(12.5)
    # An explicit cadence overrides the config (for what-ifs).
    assert trials.upgrade_payback_weeks(500, 100, 1.0) == pytest.approx(5.0)
    # Nothing gained means the spend never returns — None, not zero weeks.
    assert trials.upgrade_payback_draws(500, 0) is None
    assert trials.upgrade_payback_weeks(500, 0) is None
    assert trials.upgrade_payback_weeks(None, 100) is None


def test_probe_prices_a_single_level_bump_and_its_payback():
    # Ten members at level 113 sit exactly on the tier-8/9 edge: ONE Guild Brewery
    # level (+2 levels, 500 gp) buys tier 9 and its 100 points, repaying in 5
    # draws == 12.5 weeks.
    party = [_member(f"M{i}", {"Brewing": 113}) for i in range(10)]
    u = trials.probe_building_upgrade(party, "Brewing")
    assert u.reachable is True
    assert u.levels_needed == 1
    assert (u.from_level, u.to_level) == (0, 1)
    assert (u.skill_levels_now, u.skill_levels_after) == (0, 2)
    assert u.total_cost == 500
    assert u.next_level_cost == 500
    assert u.tier_after == u.tier_now + 1
    assert u.points_gained == config.TRIAL_POINTS_PER_TIER
    assert u.draws_to_return == pytest.approx(5.0)
    assert u.weeks_to_return == pytest.approx(12.5)
    assert u.building == "Guild Brewery"
    assert u.at_cap is False


def test_probe_counts_the_levels_needed_and_sums_their_cost():
    # A party comfortably inside a tier band needs SEVERAL levels, and the cost is
    # every step added up — not the single next step.
    party = [_member(f"M{i}", {"Brewing": 108}) for i in range(10)]
    u = trials.probe_building_upgrade(party, "Brewing")
    assert u.reachable is True
    assert u.levels_needed > 1
    assert u.to_level == u.from_level + u.levels_needed
    assert u.skill_levels_after == 2 * u.to_level
    assert u.tier_after > u.tier_now
    assert u.total_cost == trials.guild_building_upgrade_total_cost(
        u.from_level, u.to_level
    )
    assert u.total_cost > u.next_level_cost      # a multi-level climb costs more
    assert u.weeks_to_return == pytest.approx(
        u.total_cost / u.points_gained * config.TRIAL_WEEKS_BETWEEN_DRAWS
    )


def test_probe_finds_the_cheapest_bumping_level_like_a_brute_force_scan():
    # The binary search assumes the race is monotone in the building level. Pin
    # both: tier_reached never falls as levels rise, and the level the probe picks
    # is the FIRST one a linear scan would accept.
    for level in (100, 105, 110, 113, 120):
        party = [_member(f"M{i}", {"Brewing": level}) for i in range(10)]
        tiers = [
            trials.simulate_race(
                party, "Brewing", None, trials.building_skill_levels(building)
            ).tier_reached
            for building in range(config.GUILD_BUILDING_MAX_LEVEL + 1)
        ]
        assert tiers == sorted(tiers), f"non-monotone at level {level}: {tiers}"
        first = next(
            (b for b in range(1, len(tiers)) if tiers[b] > tiers[0]), None
        )
        u = trials.probe_building_upgrade(party, "Brewing")
        assert u.to_level == first
        assert u.reachable is (first is not None)


def test_probe_reports_a_tier_unreachable_at_any_level():
    # Three members at level 400 are already at the success clamp (1.0) for the
    # tier they fail, so the race is time-bound: no number of building levels
    # helps, and the probe says so rather than quoting a price.
    party = [_member(f"M{i}", {"Brewing": 400}) for i in range(3)]
    u = trials.probe_building_upgrade(party, "Brewing")
    assert u.at_cap is False                    # levels ARE available to buy
    assert u.reachable is False                 # they just do not buy a tier
    assert u.levels_needed is None
    assert (u.to_level, u.tier_after, u.points_after) == (None, None, None)
    assert u.points_gained == 0
    assert u.total_cost is None
    assert (u.draws_to_return, u.weeks_to_return) == (None, None)
    assert u.next_level_cost == 500              # still priced, for the officers


def test_probe_at_level_cap_offers_no_upgrade(monkeypatch):
    monkeypatch.setitem(
        config.GUILD_BUILDING_LEVELS, "Brewing", config.GUILD_BUILDING_MAX_LEVEL
    )
    party = [_member(f"M{i}", {"Brewing": 113}) for i in range(10)]
    u = trials.probe_building_upgrade(party, "Brewing")
    assert u.at_cap is True
    assert u.from_level == config.GUILD_BUILDING_MAX_LEVEL
    assert u.next_level_cost is None
    assert u.reachable is False
    assert u.levels_needed is None
    assert u.total_cost is None
    assert u.points_gained == 0
    assert u.weeks_to_return is None


def test_probe_respects_an_already_built_building(monkeypatch):
    # From level 6 the next step costs 3025 (the cost to REACH level 7), and the
    # climb is priced from there — the six levels already paid for are not
    # re-charged.
    monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, "Brewing", 6)
    party = [_member(f"M{i}", {"Brewing": 100}) for i in range(10)]
    u = trials.probe_building_upgrade(party, "Brewing")
    assert u.from_level == 6
    assert u.skill_levels_now == 12
    assert u.next_level_cost == 3025
    assert u.total_cost == trials.guild_building_upgrade_total_cost(6, u.to_level)
    assert u.total_cost >= 3025


def test_probe_current_result_reuse_matches_a_fresh_simulation():
    party = [_member(f"M{i}", {"Brewing": 113}) for i in range(10)]
    fresh = trials.probe_building_upgrade(party, "Brewing")
    reused = trials.probe_building_upgrade(
        party, "Brewing", None, current=trials.simulate_race(party, "Brewing")
    )
    assert fresh.to_dict() == reused.to_dict()


def test_run_week_probes_every_drawn_skill():
    members = [_member(f"M{i}", {sk: 113 for sk in config.SKILLS}) for i in range(20)]
    wk = trials.run_week(members, skills=["Brewing", "Milking"], strategy="random")
    d = wk.to_dict()["building_upgrades"]
    assert [u["skill"] for u in d] == ["Brewing", "Milking"]
    assert [u["building"] for u in d] == ["Guild Brewery", "Guild Dairy Barn"]
    # Each probe must agree with the trial it belongs to.
    for u, t in zip(d, wk.to_dict()["trials"]):
        assert u["tier_now"] == t["tier_reached"]
        assert u["points_now"] == t["points"]
        assert u["from_level"] == 0            # every building unbuilt today
        assert u["next_level_cost"] == 500
        if u["reachable"]:
            assert u["levels_needed"] >= 1
            assert u["total_cost"] > 0
            assert u["weeks_to_return"] > 0


def test_no_member_no_party_even_with_a_guild_building(monkeypatch):
    # A guild building buffs members; it cannot manufacture a level for someone
    # who has none, so an unlevelled member still contributes nothing.
    monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, "Brewing", 20)
    m = _member("Z", {"Brewing": 100})
    m.skills["Brewing"] = SkillEntry(level=None, tool=False, top=False, bot=False)
    assert trials.rate(m, "Brewing", 1) == 0.0


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
