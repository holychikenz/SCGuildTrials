"""Unit tests for the guild-trials model. No network access.

Covers equipment bonus resolution (including the Enhancing special cases and
the Bell-Farming-column = Alchemy mapping), success clamping, race-simulation
monotonicity and headcount penalty, deterministic assignment, and the points
formula. All member fixtures are built inline so nothing here touches Google
Sheets.
"""

import json
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
    #
    # The guild-wide SHRINE terms are added by hand here (and in the two tests below)
    # because member_bonuses deliberately keeps them out of `.speed` / `.efficiency`,
    # which mean "what this member owns". Writing them out separately is the point: it
    # pins that the shrine buffs enter exactly the two channels the race reads —
    # work_power and action_seconds — and nowhere else.
    m = _member(
        "Al", {"Bell Farming": 120}, {"Bell Farming": (False, False, False)}
    )
    b = trials.member_bonuses(m, "Alchemy")
    sh_speed, sh_eff = trials.guild_shrine_bonuses()
    expected = (
        trials.success(120, 1, 0.0)
        * math.floor(120 * (1 + b.efficiency + sh_eff))
        / (config.ACTION_SECONDS_DEFAULT / (1 + b.speed + sh_speed))
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
    sh_speed, sh_eff = trials.guild_shrine_bonuses()
    expected = (
        trials.success(120, 1, 0.0)
        * (1 + config.DOUBLE_CHANCE)
        * math.floor(120 * (1 + b.efficiency + sh_eff))
        / (config.ACTION_SECONDS_DEFAULT / (1 + b.speed + sh_speed))
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
    sh_speed, sh_eff = trials.guild_shrine_bonuses()
    base = (
        trials.success(120, 1, 0.0)
        * math.floor(120 * (1 + b.efficiency + sh_eff))
        / (config.ACTION_SECONDS_DEFAULT / (1 + b.speed + sh_speed))
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
# tier_clear_seconds / time_slack_fraction (the safety margin, both forms)
# ---------------------------------------------------------------------------
def test_tier_clear_seconds_is_the_last_cleared_tiers_cumulative_time():
    party = [_member(f"m{i}", {"Foraging": 120}) for i in range(10)]
    res = trials.simulate_race(party, "Foraging")
    assert res.tier_reached >= 1

    cleared = [s for s in res.timeline if s.cleared]
    assert trials.tier_clear_seconds(res) == cleared[-1].cumulative_time
    # It is within budget by definition — that is what "cleared" means — and the
    # tier that ran out of time is NOT what gets reported.
    assert trials.tier_clear_seconds(res) <= config.TRIAL_TIME_BUDGET_SECONDS
    assert cleared[-1].tier == res.tier_reached


def test_slack_fraction_is_the_clear_time_expressed_against_the_budget():
    party = [_member(f"m{i}", {"Foraging": 120}) for i in range(10)]
    res = trials.simulate_race(party, "Foraging")
    secs = trials.tier_clear_seconds(res)
    assert trials.time_slack_fraction(res) == pytest.approx(
        1.0 - secs / config.TRIAL_TIME_BUDGET_SECONDS
    )
    assert 0.0 <= trials.time_slack_fraction(res) < 1.0


def test_no_tier_banked_has_no_clear_time_and_zero_slack():
    # A party that banks nothing must never look "safe" by virtue of an empty
    # timeline: slack stays 0.0 (the optimizer's tie-break contract) and the
    # absolute form is None (there is no moment to report).
    res = trials.simulate_race([], "Foraging")
    assert trials.tier_clear_seconds(res) is None
    assert trials.time_slack_fraction(res) == 0.0


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


# ---------------------------------------------------------------------------
# Guild shrines (patch 2026-08-11: "Shrine buffs now apply inside guild Trials")
# ---------------------------------------------------------------------------
def test_only_force_and_tempo_shrines_reach_the_tier_race():
    """The three loot/XP shrines must not move a rate at ANY level.

    Rarity and Spirit buff rare-find and essence-find, Scholar buffs wisdom; none of
    them changes how fast work gets done. Getting this wrong would silently inflate
    every published tier, so it is asserted at the level cap where the error would be
    largest rather than at the guild's current level 0.
    """
    for shrine in ("rarity", "spirit", "scholar"):
        levels = {shrine: config.GUILD_SHRINE_MAX_LEVEL}
        assert trials.guild_shrine_bonuses(levels) == (0.0, 0.0), shrine
    # Force feeds efficiency only; Tempo feeds speed only.
    per = config.GUILD_SHRINE_SKILLING_BUFFS["force"][1]
    assert trials.guild_shrine_bonuses({"force": 4}) == (0.0, pytest.approx(4 * per))
    assert trials.guild_shrine_bonuses({"tempo": 4}) == (pytest.approx(4 * per), 0.0)


def test_shrine_levels_are_clamped_to_the_cap():
    cap = config.GUILD_SHRINE_MAX_LEVEL
    per = config.GUILD_SHRINE_SKILLING_BUFFS["force"][1]
    assert trials.guild_shrine_bonuses({"force": 999})[1] == pytest.approx(cap * per)
    assert trials.guild_shrine_bonuses({"force": -5})[1] == 0.0
    assert trials.guild_shrine_bonuses({})[1] == 0.0


def test_shrine_master_switch_restores_the_pre_patch_race_exactly(monkeypatch):
    """SHRINE_BUFFS_APPLY_IN_TRIALS = False must be bit-identical, not merely close.

    The one-line rollback for the whole shrine change, so it is asserted with `==`
    rather than approx: the buffs are a multiplicative term on two channels, and
    "nearly off" would leave the model quietly wrong.
    """
    party = [_member(f"m{i}", {"Foraging": 120 + i}) for i in range(8)]
    monkeypatch.setattr(config, "SHRINE_BUFFS_APPLY_IN_TRIALS", False)
    assert trials.guild_shrine_bonuses() == (0.0, 0.0)
    off = trials.simulate_race(party, "Foraging")
    off_rate = trials.rate(party[0], "Foraging", 1)

    monkeypatch.setattr(config, "GUILD_SHRINE_LEVELS", {"force": 0, "tempo": 0})
    monkeypatch.setattr(config, "SHRINE_BUFFS_APPLY_IN_TRIALS", True)
    # All-zero levels must agree with the switch being off, exactly.
    assert trials.rate(party[0], "Foraging", 1) == off_rate
    zero = trials.simulate_race(party, "Foraging")
    assert zero.credit_points == off.credit_points
    assert zero.partial_fraction == off.partial_fraction


def test_live_shrine_levels_raise_the_rate_but_grant_no_skill_levels():
    """Force + Tempo help, and they help through speed/efficiency — never levels.

    The distinction the config comment laboured: an earlier revision dismissed the
    shrines because they "grant no skill level", which was true and beside the point.
    """
    m = _member("S", {"Foraging": 120})
    b = trials.member_bonuses(m, "Foraging")
    speed, eff = trials.guild_shrine_bonuses()
    assert (speed, eff) != (0.0, 0.0), "the live capture has Force 1 and Tempo 1"
    # The member's OWN bonuses are untouched by the guild buff.
    bare = trials.member_bonuses(m, "Foraging", shrine=(0.0, 0.0))
    assert b.speed == bare.speed and b.efficiency == bare.efficiency
    # But the resolved rate is strictly higher than with the shrines removed.
    assert trials.rate(m, "Foraging", 1) > 0
    assert b.shrine_speed == speed and b.shrine_efficiency == eff
    # And the success term — which is where BuildingSkillLevels acts — is unchanged.
    assert b.building_levels == bare.building_levels


# ---------------------------------------------------------------------------
# Per-trial minimum sign-up level (patch 2026-08-11)
# ---------------------------------------------------------------------------
def test_meets_min_level_admits_everyone_when_no_minimum_is_set():
    m = _member("M", {"Foraging": 40})
    assert trials.meets_min_level(m, "Foraging", None) is True
    # No recorded level at all is still admissible while the officers set no rule --
    # absence of a constraint is not licence to invent one.
    blank = MemberRow(name="B", main_classes="", flex="", flex_levels=[], skills={})
    assert trials.meets_min_level(blank, "Foraging", None) is True
    # But an unknown level can never be SHOWN to meet a minimum, so it is excluded.
    assert trials.meets_min_level(blank, "Foraging", 1) is False


def test_meets_min_level_is_inclusive_at_the_boundary():
    m = _member("M", {"Foraging": 100})
    assert trials.meets_min_level(m, "Foraging", 100) is True
    assert trials.meets_min_level(m, "Foraging", 101) is False


def test_min_level_reads_the_members_own_level_not_the_guild_buffed_one(monkeypatch):
    """Eligibility gates on the character's level, never on a guild building's loan.

    A guild building adds BuildingSkillLevels inside the success calculation; it does
    not raise the character's skill, and the game's sign-up screen would not care if it
    did. Modelling it the other way would seat members the game refuses.
    """
    monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, "Foraging", 20)
    m = _member("M", {"Foraging": 90})
    assert trials.guild_building_skill_levels("Foraging") == 40
    assert trials.member_skill_level(m, "Foraging") == 90
    assert trials.meets_min_level(m, "Foraging", 100) is False


def test_no_ineligible_member_is_ever_seated():
    from src.optimizer import optimize

    members = [_member(f"m{i}", {"Foraging": 80 + i * 5}) for i in range(12)]
    draw = ["Foraging"]
    asg = optimize(members, draw, cap=12, strategy="proxy_greedy",
                   min_levels={"Foraging": 110})
    seated = asg.parties["Foraging"]
    assert seated, "the eligible members should still be seated"
    for m in seated:
        assert trials.member_skill_level(m, "Foraging") >= 110
    # Everyone excluded lands on the bench rather than vanishing from the roster.
    assert len(seated) + len(asg.bench) == len(members)


def test_random_strategy_also_respects_the_minimum():
    # The Phase-1 control strategy does no filtering of its own, so run_week applies
    # the game's hard constraint to it -- otherwise trials.html could publish a party
    # the guild cannot field whenever the strategy is rolled back.
    members = [_member(f"m{i}", {"Foraging": 80 + i * 5}) for i in range(12)]
    week = trials.run_week(
        members, skills=["Foraging"], cap=12, strategy="random",
        min_levels={"Foraging": 110},
    )
    for entry in week.trials[0].roster:
        assert entry.level >= 110


def test_min_levels_absent_leaves_the_assignment_untouched():
    """The feature is inert until the officers fill the cells in."""
    from src.optimizer import optimize

    members = [_member(f"m{i}", {"Foraging": 80 + i * 5}) for i in range(12)]
    draw = ["Foraging"]
    plain = optimize(members, draw, cap=8, strategy="proxy_greedy")
    for empty in (None, {}, {"Foraging": None}):
        again = optimize(members, draw, cap=8, strategy="proxy_greedy",
                         min_levels=empty)
        assert [m.name for m in again.parties["Foraging"]] == [
            m.name for m in plain.parties["Foraging"]
        ]
        assert [m.name for m in again.bench] == [m.name for m in plain.bench]


def test_min_level_advice_reproduces_the_models_own_party():
    members = [_member(f"m{i}", {"Foraging": 60 + i * 4}) for i in range(20)]
    party = members[12:]           # the twelve strongest
    advice = trials.advise_min_level(members, party, "Foraging", current=None)
    assert advice.suggested == min(
        trials.member_skill_level(m, "Foraging") for m in party
    )
    # Setting it would bar exactly the members not in the party -- no more, no fewer.
    assert advice.would_exclude == len(members) - len(party)
    assert advice.already_benched == advice.would_exclude
    assert advice.party_size == len(party)


def test_min_level_advice_is_none_for_a_party_with_no_levels():
    blank = MemberRow(name="B", main_classes="", flex="", flex_levels=[], skills={})
    advice = trials.advise_min_level([blank], [blank], "Foraging")
    assert advice.suggested is None
    assert advice.would_exclude == 0


# ---------------------------------------------------------------------------
# Partial-tier credit (patch 2026-08-11)
# ---------------------------------------------------------------------------
def _ramp_party(shift=0, n=20):
    """A party whose Foraging levels descend, shifted wholesale by ``shift``."""
    levels = [130, 128, 126, 124, 122, 120, 118, 116, 114, 112,
              110, 108, 105, 102, 100, 98, 95, 92, 90, 88]
    return [_member(f"r{i}", {"Foraging": min(200, L + shift)})
            for i, L in enumerate(levels[:n])]


def test_progress_fraction_matches_the_failed_tiers_share_of_its_target():
    r = trials.simulate_race(_ramp_party(), "Foraging")
    budget = config.TRIAL_TIME_BUDGET_SECONDS
    failed = next(s for s in r.timeline if not s.cleared)
    banked = trials.tier_clear_seconds(r) or 0.0
    assert r.partial_fraction == pytest.approx(
        (budget - banked) / failed.time_to_clear
    )
    assert 0.0 <= r.partial_fraction < 1.0
    # The inline value simulate_race computes and the read-back helper must agree
    # EXACTLY -- they are two expressions of one quantity and a drift between them
    # would put the page and the optimizer on different numbers.
    assert trials.tier_progress_fraction(r) == r.partial_fraction
    # Only the failed step carries a progress figure.
    assert failed.progress_fraction == r.partial_fraction
    assert all(s.progress_fraction is None for s in r.timeline if s.cleared)


def test_progress_fraction_is_zero_when_nothing_was_in_progress():
    # An empty party: no tier attempted at all.
    empty = trials.simulate_race([], "Foraging")
    assert empty.partial_fraction == 0.0 and empty.credit_points == 0.0
    # A party that cannot move: the failed step has no time_to_clear to divide by.
    blank = MemberRow(name="B", main_classes="", flex="", flex_levels=[], skills={})
    stuck = trials.simulate_race([blank], "Foraging")
    assert stuck.partial_fraction == 0.0 and stuck.credit_points == 0.0


def test_credit_points_reduce_to_the_step_function_when_the_rate_is_zero(monkeypatch):
    """The one-line rollback, asserted rather than asserted-in-a-comment."""
    monkeypatch.setattr(config, "TRIAL_PARTIAL_CREDIT_RATE", 0.0)
    for n in range(1, 21):
        r = trials.simulate_race(_ramp_party(n=n), "Foraging")
        assert r.credit_points == float(r.points)
        assert trials.points_for_result(r) == float(
            trials.points_for_tier(r.tier_reached)
        )


def test_credit_points_are_monotone_in_party_throughput():
    """Stronger is never worth less -- including ACROSS tier boundaries.

    The precondition for trials._cheapest_bumping_level's binary search, and the
    reason partial credit does not punish a party for crossing a boundary: completing
    a tier gains TRIAL_POINTS_PER_TIER while surrendering at most rate*PER_TIER of
    partial credit, so with rate <= 1 the step always dominates the loss.
    """
    previous = None
    for shift in range(-40, 35, 5):
        value = trials.simulate_race(_ramp_party(shift), "Foraging").credit_points
        if previous is not None:
            assert value >= previous - 1e-9, f"non-monotone at shift={shift}"
        previous = value


def test_crossing_a_tier_boundary_raises_points_by_at_least_the_residual_step():
    """The cliff is HALVED by partial credit, not removed -- which is why the
    sign-up planner's compound-reshuffle machinery still has work to do."""
    residual = config.TRIAL_POINTS_PER_TIER * (1 - config.TRIAL_PARTIAL_CREDIT_RATE)
    seen = 0
    previous = None
    for shift in range(-40, 35, 1):
        r = trials.simulate_race(_ramp_party(shift), "Foraging")
        if previous is not None and r.tier_reached > previous[0]:
            assert r.credit_points - previous[1] >= residual - 1e-9
            seen += 1
        previous = (r.tier_reached, r.credit_points)
    assert seen >= 3, "the sweep must actually cross some boundaries"


def test_the_marginal_member_is_no_longer_worth_exactly_nothing():
    """The degeneracy that shaped the optimizer, and its replacement.

    Under the step objective almost every candidate scored an identical zero -- which
    is what justified seating them all for free. NOT literally every one: a strong
    enough addition could always cross a tier boundary, and this fixture sits near one,
    so the honest claim is that the step objective is blind across a broad PLATEAU while
    partial credit resolves every candidate distinctly.
    """
    party = _ramp_party()
    base = trials.simulate_race(party, "Foraging")
    levels = (140, 120, 110, 100, 90, 80, 70, 60, 50, 40, 30, 20, 10)
    step, credit = [], []
    for level in levels:
        cand = _member("cand", {"Foraging": level})
        r = trials.simulate_race(party + [cand], "Foraging")
        step.append(r.points - base.points)
        credit.append(r.credit_points - base.credit_points)

    # THE PLATEAU: the step objective cannot tell most of these candidates apart, and
    # scores the great majority at exactly nothing.
    assert step.count(0) >= len(levels) - 2, step
    assert len(set(step)) <= 2, step

    # THE SLOPE: partial credit resolves all thirteen, strictly ordered by strength,
    # with exactly one sign change -- the break-even a seat now has to clear.
    assert all(a > b for a, b in zip(credit, credit[1:])), credit
    signs = [d > 0 for d in credit]
    assert signs[0] is True and signs[-1] is False
    assert sum(1 for a, b in zip(signs, signs[1:]) if a != b) == 1
    assert len(set(credit)) == len(credit)


def test_credit_points_are_deterministic_and_order_independent():
    """No dependence on party iteration order.

    trials._prepare_member records that a one-ULP change in a party rate once left SC
    on the same points while reshuffling every party for no gain, so this is not
    academic: a float objective that varied with roster order would make the whole
    search irreproducible.
    """
    party = _ramp_party()
    first = trials.simulate_race(party, "Foraging").credit_points
    assert trials.simulate_race(list(party), "Foraging").credit_points == first
    assert trials.simulate_race(
        list(reversed(party)), "Foraging"
    ).credit_points == first


# ---------------------------------------------------------------------------
# E[points] — the honest figure beside the optimistic one
# ---------------------------------------------------------------------------
def test_expected_points_reduces_to_the_deterministic_score_as_sigma_vanishes(
    monkeypatch,
):
    """The sigma -> 0 identity, and the licence for everything else in this block.

    With no uncertainty the expectation must BE the deterministic score, to within
    quadrature error. Asserted tightly (1e-9) because a normalised midpoint grid over
    a degenerate distribution collapses onto the single point exactly.
    """
    party = _ramp_party()
    r = trials.simulate_race(party, "Foraging")
    monkeypatch.setattr(config, "RISK_SIGMA_SYSTEMATIC", 0.0)
    monkeypatch.setattr(trials, "clear_sigma", lambda *a, **k: 0.0)
    assert trials.expected_credit_points(party, "Foraging", r) == pytest.approx(
        r.credit_points, abs=1e-9
    )


def test_expected_points_is_below_the_deterministic_score_on_a_knife_edge():
    """The whole reason this exists.

    A lineup that banks its tier with seconds to spare is a coin flip, and the
    deterministic score prices it as a certainty. Measured live, such a trial
    over-claims by ~24 points; a comfortable one by ~0.02 (and in fact slightly UNDER,
    since a favourable shock has upside). Both directions are checked here.
    """
    party = _ramp_party()
    comfortable = trials.simulate_race(party, "Foraging")
    assert trials.time_slack_fraction(comfortable) > 0.05
    e_comfortable = trials.expected_credit_points(party, "Foraging", comfortable)
    assert abs(comfortable.credit_points - e_comfortable) < 1.0

    # Shrink the party one at a time until a tier is held by a hair.
    thin = None
    for k in range(1, len(party)):
        candidate = party[: len(party) - k]
        result = trials.simulate_race(candidate, "Foraging")
        if 0 < trials.time_slack_fraction(result) < 0.01 and result.tier_reached >= 1:
            thin = (candidate, result)
            break
    assert thin is not None, "no knife-edge party found in the sweep"
    candidate, result = thin
    expected = trials.expected_credit_points(candidate, "Foraging", result)
    assert expected < result.credit_points - 5.0, (
        "a tier held by seconds must be priced well below its deterministic score"
    )
    # And never below the tier the party is nearly certain to hold.
    assert expected > trials.points_for_tier(result.tier_reached - 1)


def test_expected_points_is_switchable_off():
    party = _ramp_party()
    r = trials.simulate_race(party, "Foraging")
    original = config.RISK_EXPECTED_POINTS
    try:
        config.RISK_EXPECTED_POINTS = False
        assert trials.expected_credit_points(party, "Foraging", r) is None
    finally:
        config.RISK_EXPECTED_POINTS = original


def test_cumulative_tier_times_race_past_the_buzzer():
    """The lookahead the upside terms need, which simulate_race truncates."""
    party = _ramp_party()
    r = trials.simulate_race(party, "Foraging")
    taus = trials._cumulative_tier_times(
        party, "Foraging", r.tier_reached + config.RISK_LOOKAHEAD_TIERS
    )
    assert len(taus) == r.tier_reached + config.RISK_LOOKAHEAD_TIERS
    assert all(a < b for a, b in zip(taus, taus[1:])), "must be strictly increasing"
    # It agrees with the shipped race on every tier the race actually reported.
    for step in r.timeline:
        if step.cumulative_time is not None:
            assert taus[step.tier - 1] == pytest.approx(step.cumulative_time)
    # And it runs PAST the budget, which is the point.
    assert taus[r.tier_reached] > config.TRIAL_TIME_BUDGET_SECONDS
    # A party that cannot move has no curve at all.
    blank = MemberRow(name="B", main_classes="", flex="", flex_levels=[], skills={})
    assert trials._cumulative_tier_times([blank], "Foraging", 5) == []


# ---------------------------------------------------------------------------
# Community buffs: the 1..20 level ladder
# ---------------------------------------------------------------------------
# The magnitudes are CONFIRMED game data (client dump communityBuffTypeDetailMap,
# v1.20260715.0 — see research/community-buffs.md), so these tests pin the numbers
# themselves rather than merely re-deriving whatever config happens to hold.
def test_community_buff_ladder_matches_the_dump():
    # flatBoost at level 1, and flatBoost + 19*flatBoostLevelBonus at the cap.
    # NOTE flatBoost != flatBoostLevelBonus for these buffs, so the
    # `per_level * level` shortcut the buildings/houses/shrines use is WRONG here:
    # at level 20 that shortcut would claim 0.10 gathering, not 0.295.
    assert trials.community_buff_value("gathering", 1) == pytest.approx(0.20)
    assert trials.community_buff_value("gathering", 20) == pytest.approx(0.295)
    assert trials.community_buff_value("enhancing", 1) == pytest.approx(0.20)
    assert trials.community_buff_value("enhancing", 20) == pytest.approx(0.295)
    assert trials.community_buff_value("production", 1) == pytest.approx(0.14)
    assert trials.community_buff_value("production", 20) == pytest.approx(0.197)
    # And it is linear in between, not stepped.
    assert trials.community_buff_value("production", 5) == pytest.approx(0.152)


def test_community_buff_value_clamps_to_the_games_own_ladder():
    # Level 0 resolves to the level-1 value, NOT to zero: 1 is where the ladder
    # starts, and below it the buff does not exist rather than granting less. An
    # INACTIVE buff is a regime (calibrate.scenario_buffs_lapsed), not a level.
    # Above the cap there is nothing further to grant.
    assert trials.community_buff_value("gathering", 0) == pytest.approx(0.20)
    assert trials.community_buff_value("gathering", -5) == pytest.approx(0.20)
    assert trials.community_buff_value("gathering", 99) == pytest.approx(
        trials.community_buff_value("gathering", config.COMMUNITY_BUFF_MAX_LEVEL)
    )


def test_shipped_config_publishes_level_one():
    """The published default. Deliberately a test rather than a comment.

    This one FAILS the day someone changes the default level, which is the
    intended behaviour: the raised-buff views are counterfactuals reached by the
    selector, and moving the default silently would republish the whole site's
    plan under a regime the guild may not have funded.
    """
    assert config.COMMUNITY_BUFF_LEVEL == 1
    assert config.COMMUNITY_BUFF_MAX_LEVEL == 20
    # The level selector ships; the second optimiser run it replaced does not. Both
    # are pinned rather than assumed, because each is a one-line switch and the pair
    # is the whole trade: twenty re-rated rungs at ~2ms each, in place of one
    # re-optimised rung at ~90s.
    assert config.TRIALS_BUFF_LEVEL_SLIDER is True
    assert config.TRIALS_PUBLISH_MAXBUFF_PAGE is False


def test_run_week_ladder_rates_one_plan_at_every_rung():
    """One search, twenty ratings: same parties throughout, different numbers.

    The guarantee the whole selector rests on. If the ladder ever re-optimised, the
    rosters would diverge and the page would be writing one plan's rates into
    another plan's rows.
    """
    members = [
        _member(f"M{i}", {"Foraging": 100 + i, "Brewing": 100 + i, "Enhancing": 90 + i})
        for i in range(8)
    ]
    skills = ["Foraging", "Brewing"]
    published, ladder = trials.run_week_ladder(
        members, skills=skills, strategy="random"
    )

    assert set(ladder) == set(range(1, config.COMMUNITY_BUFF_MAX_LEVEL + 1))
    # The published rung IS the published week, not a copy that might drift.
    assert ladder[config.COMMUNITY_BUFF_LEVEL] is published
    # One build, one timestamp.
    assert {w.generated_at for w in ladder.values()} == {published.generated_at}

    def roster(week):
        return [[r.name for r in t.roster] for t in week.trials]

    for level, rung in ladder.items():
        assert rung.community_buff_level == level
        assert roster(rung) == roster(published), level
        assert [t.skill for t in rung.trials] == skills
        assert rung.bench == published.bench

    # And the rungs are not all the same number: a raised buff has to move the score
    # somewhere, or the control would be decorative.
    totals = {round(w.total_credit_points, 6) for w in ladder.values()}
    assert len(totals) > 1
    assert (
        ladder[config.COMMUNITY_BUFF_MAX_LEVEL].total_credit_points
        >= published.total_credit_points
    )


def test_run_week_ladder_restores_the_ambient_regime():
    """community_buff_level rebinds config globals; twenty of them in a loop must
    leave the process exactly as they found it."""
    before = (
        config.COMMUNITY_BUFF_LEVEL,
        config.COMMUNITY_GATHERING_BUFF_DOUBLE,
        config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF,
        config.COMMUNITY_ENHANCING_SPEED_BUFF,
        config.DOUBLE_CHANCE,
    )
    members = [_member(f"M{i}", {"Foraging": 100 + i}) for i in range(4)]
    trials.run_week_ladder(members, skills=["Foraging"], strategy="random")
    assert (
        config.COMMUNITY_BUFF_LEVEL,
        config.COMMUNITY_GATHERING_BUFF_DOUBLE,
        config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF,
        config.COMMUNITY_ENHANCING_SPEED_BUFF,
        config.DOUBLE_CHANCE,
    ) == before


def test_run_week_equals_choose_then_score():
    """The refactor's invariant: run_week is exactly its two halves, in order."""
    members = [
        _member(f"M{i}", {"Foraging": 100 + i, "Brewing": 100 + i}) for i in range(6)
    ]
    skills = ["Foraging", "Brewing"]
    whole = trials.run_week(members, skills=skills, strategy="random")
    assignment = trials.choose_assignment(members, skills=skills, strategy="random")
    halves = trials.score_assignment(
        assignment, members, skills=skills, strategy="random"
    )
    assert whole.total_credit_points == halves.total_credit_points
    assert [t.tier_reached for t in whole.trials] == [
        t.tier_reached for t in halves.trials
    ]
    assert whole.bench == halves.bench


def test_config_constants_agree_with_the_ladder_at_the_default_level():
    """config derives its three magnitudes with the literals written out, so this
    is the test that shouts if the two copies ever drift apart."""
    level = config.COMMUNITY_BUFF_LEVEL
    assert config.COMMUNITY_GATHERING_BUFF_DOUBLE == pytest.approx(
        trials.community_buff_value("gathering", level)
    )
    assert config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF == pytest.approx(
        trials.community_buff_value("production", level)
    )
    assert config.COMMUNITY_ENHANCING_SPEED_BUFF == pytest.approx(
        trials.community_buff_value("enhancing", level)
    )
    # DOUBLE_CHANCE stays the composed quantity: community buff + gear placeholder.
    assert config.DOUBLE_CHANCE == pytest.approx(
        config.COMMUNITY_GATHERING_BUFF_DOUBLE + config.GEAR_DOUBLE_CHANCE
    )


def test_community_buff_level_context_moves_every_term_the_race_reads():
    m = _member("Buffed", {"Foraging": 120, "Brewing": 120, "Enhancing": 120})
    base_forage = trials.double_chance("Foraging")
    base_brew = trials.member_bonuses(m, "Brewing").efficiency
    base_enh = trials.member_bonuses(m, "Enhancing").speed

    with trials.community_buff_level(20):
        assert trials.double_chance("Foraging") == pytest.approx(
            0.295 + config.GEAR_DOUBLE_CHANCE
        )
        # Non-gathering families still carry no doubling chance at any buff level.
        assert trials.double_chance("Brewing") == 0.0
        assert trials.member_bonuses(m, "Brewing").efficiency == pytest.approx(
            base_brew + (0.197 - 0.14)
        )
        assert trials.member_bonuses(m, "Enhancing").speed == pytest.approx(
            base_enh + (0.295 - 0.20)
        )
        # Enhancing gets SPEED, never efficiency — true at every buff level.
        assert trials.member_bonuses(m, "Enhancing").efficiency == 0.0
        assert config.COMMUNITY_BUFF_LEVEL == 20

    assert trials.double_chance("Foraging") == pytest.approx(base_forage)
    assert trials.member_bonuses(m, "Brewing").efficiency == pytest.approx(base_brew)
    assert trials.member_bonuses(m, "Enhancing").speed == pytest.approx(base_enh)
    assert config.COMMUNITY_BUFF_LEVEL == 1


def test_community_buff_level_context_restores_on_exception():
    saved = (
        config.DOUBLE_CHANCE,
        config.COMMUNITY_GATHERING_BUFF_DOUBLE,
        config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF,
        config.COMMUNITY_ENHANCING_SPEED_BUFF,
        config.COMMUNITY_BUFF_LEVEL,
    )
    with pytest.raises(RuntimeError):
        with trials.community_buff_level(20):
            raise RuntimeError("boom")
    assert (
        config.DOUBLE_CHANCE,
        config.COMMUNITY_GATHERING_BUFF_DOUBLE,
        config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF,
        config.COMMUNITY_ENHANCING_SPEED_BUFF,
        config.COMMUNITY_BUFF_LEVEL,
    ) == saved


def test_run_week_records_the_buff_regime_it_ran_under():
    # Same reason guild_building_levels is recorded: the page and the JSON state
    # the assumption instead of hiding it — and with TWO runs shipped per guild, a
    # reader holding one JSON file must be able to tell which regime made it.
    members = [_member(f"M{i}", {sk: 110 for sk in config.SKILLS}) for i in range(8)]
    skills = ["Foraging", "Brewing"]
    base = trials.run_week(members, skills=skills, strategy="random").to_dict()
    assert base["community_buff_level"] == 1
    assert base["community_buff_gathering"] == pytest.approx(0.20)
    assert base["community_buff_production"] == pytest.approx(0.14)
    assert base["community_buff_enhancing"] == pytest.approx(0.20)

    with trials.community_buff_level(config.COMMUNITY_BUFF_MAX_LEVEL):
        maxed = trials.run_week(members, skills=skills, strategy="random").to_dict()
    assert maxed["community_buff_level"] == 20
    assert maxed["community_buff_gathering"] == pytest.approx(0.295)
    assert maxed["community_buff_production"] == pytest.approx(0.197)
    assert maxed["community_buff_enhancing"] == pytest.approx(0.295)

    # Bigger buffs cannot score less: same members, same draw, same seed.
    assert maxed["total_credit_points"] >= base["total_credit_points"]


# ---------------------------------------------------------------------------
# The trials page's community-buff level switch
# ---------------------------------------------------------------------------
def _two_regime_weeks():
    """The same members and draw, run at the default level and at the cap."""
    members = [
        _member(f"M{i}", {sk: 100 + i for sk in config.SKILLS}) for i in range(10)
    ]
    skills = ["Foraging", "Brewing"]
    base = trials.run_week(members, skills=skills, strategy="random").to_dict()
    with trials.community_buff_level(config.COMMUNITY_BUFF_MAX_LEVEL):
        maxed = trials.run_week(members, skills=skills, strategy="random").to_dict()
    return base, maxed


def test_trials_page_switch_cross_links_and_marks_the_active_level():
    from src import build

    base, maxed = _two_regime_weeks()
    site = build.GUILD_SITES[0]
    default_page = build._render_trials_html(
        base, site, "",
        counterpart={"href": build.TRIALS_MAXBUFF_PAGE, "level": 20,
                     "total": maxed["total_credit_points"]},
    )
    maxbuff_page = build._render_trials_html(
        maxed, site, "",
        counterpart={"href": build.TRIALS_PAGE, "level": 1,
                     "total": base["total_credit_points"]},
    )

    # Each page marks ITS level active and links to the other.
    assert '<span class="bt-seg active" aria-current="page">Level 1' in default_page
    assert f'href="{build.TRIALS_MAXBUFF_PAGE}"' in default_page
    assert '<span class="bt-seg active" aria-current="page">Level 20' in maxbuff_page
    assert f'href="{build.TRIALS_PAGE}"' in maxbuff_page

    # Level 1 stays on the LEFT in both, so the control does not swap sides when
    # you click it, and each page quotes the other's total so the reader can see
    # the counterfactual's worth before navigating.
    for page in (default_page, maxbuff_page):
        segs = page.split('class="bt-segs">')[1].split("</span>\n")[0]
        assert segs.index("Level 1") < segs.index("Level 20")
        assert build._cp(base["total_credit_points"]) in segs
        assert build._cp(maxed["total_credit_points"]) in segs

    # Only the counterfactual is badged as one — in the tab title, the headline and
    # the name of its own JSON — so it can never be mistaken for the published plan.
    assert "community buffs L20" not in default_page.split("</title>")[0]
    assert "community buffs L20" in maxbuff_page.split("</title>")[0]
    assert f"<code>{build.TRIALS_JSON}</code>" in default_page
    assert f"<code>{build.TRIALS_MAXBUFF_JSON}</code>" in maxbuff_page


# ---------------------------------------------------------------------------
# The trials page's community-buff level SELECTOR (one plan, every rung)
# ---------------------------------------------------------------------------
def _ladder_page():
    """A rendered trials page carrying the whole inline buff ladder."""
    from src import build

    members = [
        _member(f"M{i}", {sk: 100 + i for sk in config.SKILLS}) for i in range(10)
    ]
    skills = ["Foraging", "Brewing"]
    published, rungs = trials.run_week_ladder(
        members, skills=skills, strategy="random"
    )
    week = published.to_dict()
    ladder = {str(k): v.to_dict() for k, v in rungs.items()}
    page = build._render_trials_html(week, build.GUILD_SITES[0], "", ladder=ladder)
    return build, week, ladder, page


def test_trials_page_ships_the_selector_and_every_rung_inline():
    build, week, ladder, page = _ladder_page()

    assert 'id="buff-range"' in page
    assert f'data-published="{week["community_buff_level"]}"' in page
    assert f'max="{config.COMMUNITY_BUFF_MAX_LEVEL}"' in page
    # The ladder is a SECOND island, so the search index stays the small thing that
    # is parsed on every keystroke.
    assert 'id="levels-data"' in page
    assert 'id="assign-data"' in page

    blob = page.split('<script id="levels-data" type="application/json">')[1]
    payload = json.loads(blob.split("</script>")[0])
    assert set(payload) == set(ladder)
    for level, rung in payload.items():
        assert len(rung["cards"]) == len(week["trials"])
        assert set(rung["assign"]) == {t["skill"] for t in week["trials"]}
        for card, trial in zip(rung["cards"], week["trials"]):
            assert len(card["rates"]) == len(trial["roster"])


def test_selector_says_the_rungs_are_a_lower_bound():
    """The one claim the control MUST make. Re-rating a fixed plan understates what
    the guild could score at a raised level, because the optimiser would reseat —
    and a reader who mistakes the floor for the forecast under-invests."""
    _, _, _, page = _ladder_page()
    note = page.split('class="bl-note"')[1].split("</p>")[0]
    assert "lower\n       bound" in note or "lower bound" in note
    assert "parties never change" in note


def test_ladder_payload_keeps_the_published_row_order():
    """Rows carry ids assigned from the PUBLISHED sort order. A rung re-sorted by
    its own rates would write each member's numbers into a stranger's row."""
    build, week, ladder, _ = _ladder_page()
    payload = build._buff_ladder_payload(week, ladder)
    top = str(config.COMMUNITY_BUFF_MAX_LEVEL)

    for t_index, trial in enumerate(week["trials"]):
        order = [r["name"] for r in build._sorted_roster(trial)]
        rung = ladder[top]["trials"][t_index]
        by_name = {r["name"]: r for r in rung["roster"]}
        expected = [
            [build._num(by_name[n]["rate_tier1"]), build._num(by_name[n]["rate_final"])]
            for n in order
        ]
        assert payload[top]["cards"][t_index]["rates"] == expected

    # The level-20 roster genuinely IS in a different rate order from the level-1
    # one for at least one trial, or this test would pass on a tautology.
    reordered = any(
        [r["name"] for r in build._sorted_roster(week["trials"][i])]
        != [r["name"] for r in build._sorted_roster(ladder[top]["trials"][i])]
        for i in range(len(week["trials"]))
    ) or any(
        build._num(r["rate_final"]) != build._num(s["rate_final"])
        for i in range(len(week["trials"]))
        for r, s in zip(
            build._sorted_roster(week["trials"][i]),
            build._sorted_roster(ladder[top]["trials"][i]),
        )
    )
    assert reordered


def test_published_rung_matches_the_server_rendered_page():
    """The selector's default rung and the HTML it sits on are one render, so
    sliding away and back cannot change a single figure."""
    build, week, ladder, page = _ladder_page()
    payload = build._buff_ladder_payload(week, ladder)
    here = payload[str(week["community_buff_level"])]

    assert here["strip"] == build._stat_strip(week)
    for t_index, trial in enumerate(week["trials"]):
        card = here["cards"][t_index]
        assert card["head"] == build._card_headline(trial)
        assert card["safe"] == build._card_safety(trial)
        assert card["rh"] == build._rate_header(trial)
        # And those fragments are the ones actually on the page, in their slots.
        assert f'id="c{t_index}-head">{card["head"]}</p>' in page
        assert f'id="c{t_index}-tl">{build._timeline_rows(trial)}</tbody>' in page


def test_no_ladder_renders_the_page_exactly_as_before():
    """The rollback. TRIALS_BUFF_LEVEL_SLIDER = False passes ladder=None, and no
    control, no ladder and no island reach the page."""
    build, week, _, _ = _ladder_page()
    bare = build._render_trials_html(week, build.GUILD_SITES[0], "", ladder=None)
    body = bare.split("<body>")[1].split('<script id="assign-data"')[0]
    assert 'id="buff-range"' not in body
    assert 'class="bl-note"' not in body
    assert '<script id="levels-data"' not in bare
    # Still a complete page, with the numbers it always had.
    assert build._stat_strip(week) in bare
    # The page script ships whole either way and simply finds nothing to bind to:
    # one JS payload for both regimes, so the two can never drift apart. It must
    # therefore be safe for it to look for a control that is not there.
    assert 'document.getElementById("levels-data")' in bare
    assert "if (LEVELS && lvlBox && lvlRange)" in bare


def test_trials_page_footnote_states_the_level_it_was_built_at():
    from src import build

    base, maxed = _two_regime_weeks()
    site = build.GUILD_SITES[0]
    assert "level 1</strong>" in build._render_trials_html(base, site)
    assert "level 20</strong>" in build._render_trials_html(maxed, site)


def test_trials_page_renders_without_a_counterpart():
    """A lone render (no sibling regime) emits no switch at all rather than half
    of one — the path any caller holding a single WeekResult takes."""
    from src import build

    base, _ = _two_regime_weeks()
    body = build._render_trials_html(base, build.GUILD_SITES[0]).split("</style>", 1)[1]
    assert "bufftoggle" not in body
    assert "bt-seg" not in body


def test_trials_page_switch_survives_a_pre_buff_trials_json():
    """A trials.json written before this feature carries no community_buff_level;
    the page must still render, minus the switch, rather than raise."""
    from src import build

    base, _ = _two_regime_weeks()
    del base["community_buff_level"]
    page = build._render_trials_html(
        base, build.GUILD_SITES[0], "",
        counterpart={"href": build.TRIALS_MAXBUFF_PAGE, "level": 20, "total": 1.0},
    )
    assert "bufftoggle" not in page.split("</style>", 1)[1]


# ---------------------------------------------------------------------------
# Pinned members
# ---------------------------------------------------------------------------
# Most readers want one fact from this page -- which trial am I in, and is it
# safe -- so a member can be pinned to a panel at the top that survives the next
# visit. The state lives in the reader's browser, which the suite cannot execute;
# what it CAN pin down is the contract the page script depends on, and every test
# below guards a way that contract could silently rot.


def _pin_index(page: str) -> list[dict]:
    """The embedded assignment index the pinned panel and search both read."""
    import json

    blob = page.split('id="assign-data"', 1)[1].split(">", 1)[1].split("</script>", 1)[0]
    return json.loads(blob.replace("\\u003c", "<"))


def test_pin_key_is_namespaced_per_guild():
    """THE failure this feature is most likely to ship with.

    Both guild sites are served from ONE github.io origin -- Survey Corps at the
    root and Lactose Intolerance under /li/ -- and localStorage is scoped to the
    origin, not the directory. An unqualified key would therefore have the two
    guilds overwrite each other's pins, and the bug would surface only for the
    handful of readers who visit both.
    """
    from src import build

    base, _ = _two_regime_weeks()
    keys = {
        site.key: build._render_trials_html(base, site)
        .split('data-pin-key="', 1)[1]
        .split('"', 1)[0]
        for site in build.GUILD_SITES
    }
    assert len(set(keys.values())) == len(build.GUILD_SITES), keys
    for guild_key, pin_key in keys.items():
        assert pin_key.endswith("." + guild_key)


def test_roster_rows_sort_on_the_bare_name_not_the_star():
    """The pin control lives INSIDE the member cell, so that cell's textContent
    now starts with a star glyph. The client-side text sorter falls back to
    textContent when data-sort is absent, which would make every member's sort key
    identical; the attribute carries the bare name to prevent it."""
    from src import build

    base, _ = _two_regime_weeks()
    page = build._render_trials_html(base, build.GUILD_SITES[0])
    names = [e["n"] for e in _pin_index(page) if e["t"] != "Bench"]
    assert names
    for name in names:
        assert f'<th scope=row data-sort="{name}">' in page
        assert f'data-fav="{name}"' in page


def test_pinned_panel_ships_hidden_and_empty():
    """No pin can be known at build time -- the page is a static file cached by
    GitHub Pages and the pins are per-device -- so it must ship hidden, with every
    star hollow, and be filled in by the script. Shipping it visible would show a
    first-time reader an empty box; shipping a star pre-filled would show them
    somebody else's pins."""
    from src import build

    base, _ = _two_regime_weeks()
    page = build._render_trials_html(base, build.GUILD_SITES[0])
    assert '<section class="card pinned" id="pinned-section" hidden>' in page
    assert '<div id="pinned-list" class="pin-list"></div>' in page
    assert 'aria-pressed="true"' not in page
    assert page.count('class="fav" data-fav=') == len(_pin_index(page))


def test_assign_index_carries_the_pinned_panel_summary_as_plain_text():
    """The panel writes these fields with textContent, so an HTML entity would
    render literally as '&middot;'. They must be plain text, and every entry must
    carry the full set of keys -- a missing one shows as 'undefined' to a reader."""
    from src import build

    base, _ = _two_regime_weeks()
    entries = _pin_index(build._render_trials_html(base, build.GUILD_SITES[0]))
    assert entries
    for e in entries:
        assert set(e) == {"n", "t", "r", "l", "d", "m", "b"}
        for field in ("d", "m"):
            assert "&" not in e[field], e
        assert e["b"] in ("", "ok-text", "warn-text", "danger-text")


def test_pinned_summary_bands_agree_with_the_trial_card():
    """A pinned row quotes the same margin as the trial card it summarises, in the
    same colour. Deriving both from _margin_view is what keeps them honest; this
    fails the moment someone recomputes one of them separately."""
    from src import build

    base, _ = _two_regime_weeks()
    entries = _pin_index(build._render_trials_html(base, build.GUILD_SITES[0]))
    by_trial = {e["t"]: e for e in entries if e["t"] != "Bench"}
    for trial in base["trials"]:
        e = by_trial.get(trial["skill"])
        if e is None:
            continue  # an empty party seats nobody to pin
        view = build._margin_view(trial)
        assert e["b"] == build._slack_band(view["slack_fraction"])
        assert build._cp(build._credit_points(trial)) in e["d"]


def test_benched_members_can_be_pinned_too():
    """'Am I in this week?' is exactly the question the bench answers, so a benched
    member gets a star like anyone else -- and an index entry that says plainly
    they are not in a trial rather than leaving the panel blank."""
    from src import build

    base, _ = _two_regime_weeks()
    base["bench"] = ["Benched McBenchface"]
    page = build._render_trials_html(base, build.GUILD_SITES[0])
    assert 'data-fav="Benched McBenchface"' in page
    entry = next(e for e in _pin_index(page) if e["n"] == "Benched McBenchface")
    assert entry["t"] == "Bench"
    assert entry["r"] == "bench-section"
    assert entry["d"] == "Not assigned to a trial this week"


def test_pin_controls_reach_every_page_the_reader_can_land_on():
    """The counterfactual page shares the guild's pins (one key, both pages), so it
    needs the same controls -- landing on it from the buff switch must not lose
    them."""
    from src import build

    base, maxed = _two_regime_weeks()
    page = build._render_trials_html(
        maxed, build.GUILD_SITES[0], "",
        counterpart={"href": build.TRIALS_PAGE, "level": 1,
                     "total": base["total_credit_points"]},
    )
    assert 'id="pinned-section"' in page
    assert 'data-pin-key="guild-trials.pins.sc"' in page


# ---------------------------------------------------------------------------
# Per-guild party cap (config.TRIAL_PARTY_CAPS, split 2026-08-21)
# ---------------------------------------------------------------------------
def test_every_guild_site_resolves_its_own_party_cap():
    """Each shipped guild has a cap of its own, and SC's is the larger.

    The cap was ONE constant for both guilds until the guilds diverged. This
    pins the two facts a silent regression would break: that every GuildSite
    resolves (rather than raising, or falling through to the guild-less
    default), and that the two guilds are genuinely different — so a future
    edit that collapses the map back into one number fails here.
    """
    from src import build

    caps = {site.key: site.party_cap for site in build.GUILD_SITES}
    assert caps == {"sc": 28, "li": 26}
    assert config.party_cap("sc") == 28
    assert config.party_cap("li") == 26


def test_an_unknown_guild_key_raises_rather_than_defaulting():
    """A typo'd guild key must NOT quietly plan against the fallback cap: a plan
    built for the wrong seat count is indistinguishable from a good one."""
    with pytest.raises(KeyError):
        config.party_cap("survey-corps")


def test_the_compute_unit_plans_at_the_guilds_own_cap():
    """The end of the plumbing: the cap on the job reaches the WeekResult.

    ``_unit_jobs`` resolves each guild's cap in the parent and ``_compute_unit``
    hands it to ``run_week``; if either link is dropped the week silently
    reverts to config.TRIAL_PARTY_CAP and only SC's page would be wrong.
    """
    from src import build

    members = [_member(f"M{i}", {"Foraging": 100}) for i in range(40)]
    for site in build.GUILD_SITES:
        job = {
            "site_key": site.key,
            "members": members,
            "skills": ["Foraging"],
            "min_levels": {},
            "cap": site.party_cap,
            "level": 1,
            "picks": None,
        }
        out = build._compute_unit(job)
        assert out["week"]["cap"] == site.party_cap
        assert len(out["week"]["trials"][0]["roster"]) <= site.party_cap


# ===========================================================================
# Roster phase R3 — the tool table, and per-member shrines
# ===========================================================================
import json as _json  # noqa: E402
import os as _os  # noqa: E402

from src.reader import SheetStructureError as _SheetStructureError  # noqa: E402


def _roster_member(name="r1", skill="Milking", level=110, item=None, enhance=None,
                   tool=False, top=False, bot=False, house=4, shrines=None):
    """A member carrying roster-sourced tool and shrine facts."""
    entry = SkillEntry(level=level, tool=tool, top=top, bot=bot, house=house)
    entry.tool_item = item
    entry.tool_enhance = enhance
    m = MemberRow(
        name=name, main_classes="", flex="", flex_levels=[],
        skills={
            s: (entry if s == skill else SkillEntry(
                level=level, tool=tool, top=top, bot=bot, house=house))
            for s in config.SKILLS
        },
    )
    if shrines:
        m.shrine_levels = dict(shrines)
    return m


# --- the tool table ---------------------------------------------------------
def test_tool_table_reproduces_the_four_shipped_constants_at_plus7():
    """Exact ==, not approx: a one-ULP change reshuffles every party."""
    assert trials.tool_bonus("Milking", "Holy Brush", 7) == (
        config.TOOL_SPEED_HOLY_PLUS7, 0.0)
    assert trials.tool_bonus("Milking", "Celestial Brush", 7) == (
        config.TOOL_SPEED_CELESTIAL_PLUS7, 0.0)
    assert trials.tool_bonus("Enhancing", "Holy Enhancer", 7) == (
        0.0, config.TOOL_SUCCESS_HOLY_PLUS7)
    assert trials.tool_bonus("Enhancing", "Celestial Enhancer", 7) == (
        0.0, config.TOOL_SUCCESS_CELESTIAL_PLUS7)


def test_tool_table_matches_item_stats_json():
    """The pinning test: regenerate from the research JSON and compare."""
    path = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "research", "item-stats.json",
    )
    with open(path, encoding="utf-8") as fh:
        data = _json.load(fh)

    slot_to_skill = {
        "milking_tool": "Milking", "foraging_tool": "Foraging",
        "woodcutting_tool": "Woodcutting", "cheesesmithing_tool": "C.Smithing",
        "crafting_tool": "Crafting", "tailoring_tool": "Tailoring",
        "cooking_tool": "Cooking", "brewing_tool": "Brewing",
        "alchemy_tool": "Bell Farming", "enhancing_tool": "Enhancing",
    }
    stat_key = {
        "Milking": ("milkingSpeed", "speed"),
        "Foraging": ("foragingSpeed", "speed"),
        "Woodcutting": ("woodcuttingSpeed", "speed"),
        "C.Smithing": ("cheesesmithingSpeed", "speed"),
        "Crafting": ("craftingSpeed", "speed"),
        "Tailoring": ("tailoringSpeed", "speed"),
        "Cooking": ("cookingSpeed", "speed"),
        "Brewing": ("brewingSpeed", "speed"),
        "Bell Farming": ("alchemySpeed", "speed"),
        "Enhancing": ("enhancingSuccess", "success"),
    }
    expected = {}
    for item in data["items"].values():
        skill = slot_to_skill.get(item.get("slot", ""))
        if skill is None:
            continue
        stat, channel = stat_key[skill]
        expected[item["name"]] = (
            skill, channel,
            round(item["noncombatStats"][stat], 12),
            round(item["noncombatEnhancementBonuses"][stat], 12),
        )
    assert config.TOOL_STATS == expected
    assert len(expected) == 80  # 8 tiers x 10 skills

    # And the multiplier curve, VERBATIM — calibrate reads the same array from
    # the same file, so a normalisation here would split the two apart.
    assert config.ENHANCEMENT_MULT_TABLE == data["enhancement"][
        "enhancementLevelTotalBonusMultiplierTable"]
    assert config.ENHANCEMENT_MULT_TABLE[7] == config.ENHANCEMENT_MULT_PLUS7
    assert config.ENHANCEMENT_MULT_TABLE[3] == config.ENHANCEMENT_MULT_PLUS3


def test_tool_table_carries_no_loot_or_xp_stats():
    """RareFind and Experience are real and are not part of a RATE model.

    Same rule guild_shrine_bonuses applies to Rarity, Spirit and Scholar.
    """
    for name, (skill, channel, base, per) in config.TOOL_STATS.items():
        assert channel in ("speed", "success"), name
        assert skill in config.SKILLS, name
    # Celestial tools grant all three stats; only the speed one is here, and a
    # Celestial Brush priced at +0 must be its speed base, not its rare-find one.
    assert trials.tool_bonus("Milking", "Celestial Brush", 0) == (1.05, 0.0)


def test_rainbow_tool_is_priced_between_burble_and_holy():
    """A tier the manual checkbox cannot express at all."""
    burble = trials.tool_bonus("Crafting", "Burble Chisel", 5)[0]
    rainbow = trials.tool_bonus("Crafting", "Rainbow Chisel", 5)[0]
    holy = trials.tool_bonus("Crafting", "Holy Chisel", 5)[0]
    assert burble < rainbow < holy


def test_enhancing_tool_feeds_success_not_speed():
    for tier in ("Cheese", "Verdant", "Azure", "Burble", "Crimson", "Rainbow",
                 "Holy", "Celestial"):
        speed, success = trials.tool_bonus("Enhancing", f"{tier} Enhancer", 7)
        assert speed == 0.0, tier
        assert success > 0.0, tier


def test_enhancement_level_zero_is_the_base_stat():
    assert trials.tool_bonus("Milking", "Holy Brush", 0) == (0.9, 0.0)


def test_enhancement_level_is_clamped_to_the_table():
    top = trials.tool_bonus("Milking", "Holy Brush", 20)
    assert trials.tool_bonus("Milking", "Holy Brush", 99) == top
    assert trials.tool_bonus("Milking", "Holy Brush", -5) == (0.9, 0.0)


def test_blank_enhancement_uses_the_configured_default(monkeypatch):
    monkeypatch.setattr(config, "TOOL_ENHANCE_WHEN_UNKNOWN", 0)
    assert trials.tool_bonus("Milking", "Holy Brush", None) == (0.9, 0.0)
    monkeypatch.setattr(config, "TOOL_ENHANCE_WHEN_UNKNOWN", 7)
    assert trials.tool_bonus("Milking", "Holy Brush", None) == (
        config.TOOL_SPEED_HOLY_PLUS7, 0.0)


def test_unknown_tool_item_returns_none_rather_than_guessing_a_tier():
    assert trials.tool_bonus("Milking", "Obsidian Brush", 7) is None


def test_tool_slot_mismatch_is_a_structure_error():
    """A shifted header row, which reading by NAME cannot detect."""
    with pytest.raises(_SheetStructureError) as exc:
        trials.tool_bonus("Milking", "Celestial Spatula", 7)
    assert "Cooking" in str(exc.value)
    assert "Milking" in str(exc.value)


def test_alchemy_tool_resolves_through_the_bell_farming_column():
    assert trials.tool_bonus("Alchemy", "Holy Alembic", 7)[0] == pytest.approx(1.0638)


# --- the precedence ladder inside member_bonuses ---------------------------
def test_member_bonuses_is_unchanged_when_the_skill_entry_has_no_roster_fields():
    """Exact ==; this is what lets the ~110 existing bonus tests stand."""
    plain = _roster_member(tool=True)
    b = trials.member_bonuses(plain, "Milking")
    assert b.speed == config.CAPE_SPEED_PLUS3 + config.TOOL_SPEED_CELESTIAL_PLUS7


def test_roster_tool_overrides_the_checkbox():
    m = _roster_member(item="Rainbow Brush", enhance=4, tool=True)
    b = trials.member_bonuses(m, "Milking")
    expected = trials.tool_bonus("Milking", "Rainbow Brush", 4)[0]
    assert b.speed == config.CAPE_SPEED_PLUS3 + expected


def test_switching_tools_off_restores_the_checkbox(monkeypatch):
    monkeypatch.setattr(config, "ROSTER_USE_TOOLS", False)
    m = _roster_member(item="Cheese Brush", enhance=0, tool=True)
    b = trials.member_bonuses(m, "Milking")
    assert b.speed == config.CAPE_SPEED_PLUS3 + config.TOOL_SPEED_CELESTIAL_PLUS7


def test_switching_enhancement_off_keeps_the_tier_at_plus7(monkeypatch):
    monkeypatch.setattr(config, "ROSTER_USE_TOOL_ENHANCEMENT", False)
    m = _roster_member(item="Rainbow Brush", enhance=0)
    b = trials.member_bonuses(m, "Milking")
    expected = trials.tool_bonus("Milking", "Rainbow Brush",
                                 config.ENHANCEMENT_ASSUMED_LEVEL)[0]
    assert b.speed == config.CAPE_SPEED_PLUS3 + expected


def test_unknown_tool_item_falls_back_to_the_checkbox_in_the_hot_path():
    m = _roster_member(item="Obsidian Brush", enhance=9, tool=True)
    b = trials.member_bonuses(m, "Milking")
    assert b.speed == config.CAPE_SPEED_PLUS3 + config.TOOL_SPEED_CELESTIAL_PLUS7


def test_enhancing_roster_tool_feeds_success_not_speed():
    m = _roster_member(skill="Enhancing", item="Rainbow Enhancer", enhance=6)
    b = trials.member_bonuses(m, "Enhancing")
    assert b.success_bonus == trials.tool_bonus(
        "Enhancing", "Rainbow Enhancer", 6)[1]


# --- the tool audit ---------------------------------------------------------
def test_unknown_tool_item_is_counted_and_stripped():
    m = _roster_member(item="Obsidian Brush", enhance=9)
    m.provenance = {"Milking.tool": "roster"}
    audit = trials.audit_roster_tools([m])
    assert audit.unknown_items == {"Obsidian Brush": 1}
    assert audit.unknown_members == ["r1"]
    assert m.skills["Milking"].tool_item is None
    assert "unknown item: Obsidian Brush" in m.provenance["Milking.tool"]


def test_unknown_tool_item_is_fatal_when_the_switch_says_so(monkeypatch):
    monkeypatch.setattr(config, "ROSTER_UNKNOWN_TOOL_FATAL", True)
    m = _roster_member(item="Obsidian Brush", enhance=9)
    with pytest.raises(_SheetStructureError):
        trials.audit_roster_tools([m])


def test_audit_raises_on_a_tool_in_the_wrong_slot():
    m = _roster_member(item="Celestial Spatula", enhance=7)
    with pytest.raises(_SheetStructureError):
        trials.audit_roster_tools([m])


def test_audit_counts_blank_enhancements():
    m = _roster_member(item="Holy Brush", enhance=None)
    audit = trials.audit_roster_tools([m])
    assert audit.blank_enhancements == 1
    assert audit.roster_tools == 1
    assert audit.unknown_count == 0


# --- shrines: the bit-exactness cases come first ---------------------------
def _shrine_party():
    return [
        _roster_member(name=f"s{i}", level=100 + i, tool=(i % 2 == 0))
        for i in range(6)
    ]


def test_shrines_off_is_bit_identical_to_the_hoisted_path(monkeypatch):
    """Removing simulate_race's once-per-race hoist must change nothing under it."""
    party = _shrine_party()
    monkeypatch.setattr(config, "ROSTER_USE_SHRINES", False)
    off = trials.simulate_race(party, "Milking")
    monkeypatch.setattr(config, "ROSTER_USE_SHRINES", True)
    on = trials.simulate_race(party, "Milking")  # no member carries shrine levels
    assert off.to_dict() == on.to_dict()


def test_shrine_bonuses_stay_out_of_member_speed_and_efficiency():
    """MemberBonuses must keep saying what the MEMBER owns.

    The test that catches a well-meaning fold of the shrine terms into
    b.speed / b.efficiency — which re-associates arithmetic that
    _prepare_member's docstring records as having reshuffled every SC party.
    """
    m = _roster_member(shrines={"force": 4, "tempo": 4})
    b = trials.member_bonuses(m, "Milking")
    per = config.GUILD_SHRINE_SKILLING_BUFFS["force"][1]
    assert b.shrine_efficiency == pytest.approx(4 * per)
    assert b.shrine_speed == pytest.approx(4 * per)
    assert b.speed == config.CAPE_SPEED_PLUS3 + config.TOOL_SPEED_HOLY_PLUS7
    assert b.efficiency == (
        config.ARMOUR_EFFICIENCY_PLUS7
        + config.HOUSE_EFFICIENCY_PER_LEVEL * 4
    )


def test_prepare_member_addition_order_is_preserved():
    """Exact ==, against a hand-computed floor(work_power(level, eff + shrine))."""
    m = _roster_member(shrines={"force": 3, "tempo": 2})
    b = trials.member_bonuses(m, "Milking")
    prepared = trials._prepare_member(m, "Milking", b.building_levels)
    assert prepared[4] == math.floor(
        trials.work_power(b.level, b.efficiency + b.shrine_efficiency))
    assert prepared[5] == trials.action_seconds(
        "Milking", b.speed + b.shrine_speed)


def test_member_shrine_bonuses_uses_the_members_own_level():
    per = config.GUILD_SHRINE_SKILLING_BUFFS["force"][1]
    m = _roster_member(shrines={"force": 4, "tempo": 0})
    speed, efficiency = trials.member_shrine_bonuses(m)
    assert efficiency == pytest.approx(4 * per)
    assert speed == 0.0


def test_only_force_and_tempo_reach_the_race_per_member():
    """The per-member twin of the guild-wide rule. Loot and XP stay out."""
    m = _roster_member(shrines={
        "force": 0, "tempo": 0, "spirit": 5, "rarity": 5, "scholar": 5})
    assert trials.member_shrine_bonuses(m) == (0.0, 0.0)


def test_member_shrine_level_zero_lowers_the_rate_against_the_modelled_one():
    """The five SC and ten LI members the current model OVERSTATES."""
    zero = _roster_member(name="z", shrines={"force": 0, "tempo": 0})
    one = _roster_member(name="o", shrines={"force": 1, "tempo": 1})
    assert trials.rate(zero, "Milking", 8) < trials.rate(one, "Milking", 8)


def test_shrine_levels_are_clamped_to_the_max():
    per = config.GUILD_SHRINE_SKILLING_BUFFS["force"][1]
    m = _roster_member(shrines={"force": 999, "tempo": -5})
    speed, efficiency = trials.member_shrine_bonuses(m)
    assert efficiency == pytest.approx(config.GUILD_SHRINE_MAX_LEVEL * per)
    assert speed == 0.0


def test_shrine_buffs_apply_in_trials_false_zeroes_the_per_member_path_too(
    monkeypatch,
):
    monkeypatch.setattr(config, "SHRINE_BUFFS_APPLY_IN_TRIALS", False)
    m = _roster_member(shrines={"force": 4, "tempo": 4})
    assert trials.member_shrine_bonuses(m) == (0.0, 0.0)


def test_blank_shrine_column_falls_back_to_the_guild_map():
    """Degrades per SHRINE, not per member."""
    per = config.GUILD_SHRINE_SKILLING_BUFFS["force"][1]
    m = _roster_member(shrines={"tempo": 4})  # force absent
    speed, efficiency = trials.member_shrine_bonuses(m)
    assert efficiency == pytest.approx(trials.guild_shrine_level("force") * per)
    assert speed == pytest.approx(4 * per)


def test_member_shrine_overrides_price_a_hypothetical_without_mutating():
    m = _roster_member(shrines={"force": 2, "tempo": 2})
    per = config.GUILD_SHRINE_SKILLING_BUFFS["force"][1]
    speed, efficiency = trials.member_shrine_bonuses(m, {"force": 4, "tempo": 4})
    assert efficiency == pytest.approx(4 * per)
    assert m.shrine_levels == {"force": 2, "tempo": 2}
