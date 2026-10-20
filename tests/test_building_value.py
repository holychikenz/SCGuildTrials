"""The combat building-value tab reader and the buildings.json artefact."""

import csv
import io

import pytest

from src import build, config
from src import building_value as bv
from src import trials as trials_model
from src.reader import SheetStructureError


def _row(**o):
    base = {
        "Upgrade": "Dojo", "Hrid": "/guild_buildings/dojo", "Level": "5",
        "Next Level": "6", "GP Cost": "4000", "Gain GP Per Run": "40",
        "Gain GP Lo": "20", "Gain GP Hi": "60", "Gain Pct": "0.008",
        "Gain Pct Lo": "0.004", "Gain Pct Hi": "0.012", "Runs Per Week": "2",
        "Gain GP Per Week": "80", "Payback Runs": "100", "Payback Weeks": "50",
        "GP Per Percent": "5000", "Verdict": "positive", "Rank": "1",
        "Recommendation": "buy first", "Seeds": "8", "Guild Id": "4",
        "Cycle": "2026-W36", "Generated At": "2026-10-07T10:00:00Z",
    }
    base.update(o)
    return [base[h] for h in config.BUILDING_VALUE_HEADERS]


def _csv(*rows, header=config.BUILDING_VALUE_HEADERS):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def test_header_matches_the_writer():
    # SCLIRoster optimizer/src/publish/buildingTab.js HEADER, verbatim.
    assert config.BUILDING_VALUE_HEADERS[0] == "Upgrade"
    assert len(config.BUILDING_VALUE_HEADERS) == 23


def test_empty_and_header_only_are_unobserved():
    assert bv.parse_building_value("", "sc").observed is False
    assert bv.parse_building_value(_csv(), "sc").observed is False


def test_rows_parse_with_numbers_and_rank_order():
    text = _csv(
        _row(Upgrade="Armory", Hrid="/guild_buildings/armory", Rank="",
             Recommendation="no measurable gain", **{"Payback Weeks": ""}),
        _row(),
        _row(Upgrade="Gym", Hrid="/guild_buildings/gym", Rank="2",
             Recommendation="worth buying", **{"GP Cost": "10,000"}),
    )
    got = bv.parse_building_value(text, "sc")
    assert got.observed and got.cycle == "2026-W36"
    assert [r["hrid"].split("/")[-1] for r in got.rows] == ["dojo", "gym", "armory"]
    dojo = got.rows[0]
    assert dojo["cost"] == 4000.0 and dojo["payback_weeks"] == 50.0
    assert dojo["level"] == 5 and dojo["rank"] == 1 and dojo["kind"] == "combat"
    assert got.rows[1]["cost"] == 10000.0
    assert got.rows[2]["payback_weeks"] is None and got.rows[2]["rank"] is None


def test_wrong_tab_another_guild_and_a_bad_hrid_are_refused():
    with pytest.raises(SheetStructureError, match="header"):
        bv.parse_building_value("Member,Trial Hrid,Team\nx,y,z\n", "sc")
    with pytest.raises(SheetStructureError, match="another guild"):
        bv.parse_building_value(_csv(_row(**{"Guild Id": "240"})), "sc")
    with pytest.raises(SheetStructureError, match="not a guild building"):
        bv.parse_building_value(_csv(_row(Hrid="/items/x")), "sc")


def _site():
    return next(s for s in build.GUILD_SITES if s.key == "sc")


def test_buildings_artefact_ranks_every_kind_on_one_payback_scale():
    inputs = build._GuildInputs.__new__(build._GuildInputs)
    inputs.building_value = bv.parse_building_value(_csv(_row()), "sc")
    inputs.building_value_unavailable = ""
    week = {
        "building_upgrades": [
            {"skill": "Milking", "building": "Guild Dairy Barn", "from_level": 0,
             "to_level": 1, "levels": 1, "total_cost": 2075, "points_gained": 100,
             "weeks_to_return": 51.875},
            {"skill": "Cooking", "building": "Guild Kitchen", "from_level": 20,
             "to_level": None, "levels": 0, "total_cost": None, "points_gained": 0,
             "weeks_to_return": None},
        ],
        "shrine_upgrades": [
            {"shrine": "force", "name": "Shrine of Force", "from_level": 4,
             "next_level_cost": 3300, "points_gained_at_full_adoption": 0.95,
             "weeks_to_return": 3477.9},
        ],
    }
    doc = build._buildings_artefact(_site(), inputs, week)
    assert doc["gp_basis"] == "base" and doc["payback_unit"] == "weeks"
    assert doc["combat"]["available"] is True
    assert [(r["kind"], r["rank"]) for r in doc["ranked"]] == [
        ("combat", 1), ("skilling", 2), ("shrine", 3)]
    milk = doc["ranked"][1]
    assert milk["gain_gp_per_week"] == pytest.approx(100 / config.TRIAL_WEEKS_BETWEEN_DRAWS)
    assert doc["ranked"][0]["recommendation"] == "buy first"
    assert len(doc["skilling"]["upgrades"]) == 2   # carried verbatim, maxed one too


def test_buildings_artefact_without_the_tab_still_ranks_skilling():
    inputs = build._GuildInputs.__new__(build._GuildInputs)
    inputs.building_value = None
    inputs.building_value_unavailable = "never written"
    doc = build._buildings_artefact(_site(), inputs, {"building_upgrades": [
        {"skill": "Milking", "building": "Guild Dairy Barn", "from_level": 0,
         "to_level": 1, "levels": 1, "total_cost": 2075, "points_gained": 100,
         "weeks_to_return": 51.875}]})
    assert doc["combat"]["available"] is False
    assert doc["combat"]["unavailable"] == "never written"
    assert [r["kind"] for r in doc["ranked"]] == ["skilling"]


BH, TREASURY = config.BUILDERS_HALL_HRID, config.TREASURY_HRID


def _utility_doc(levels, total=5000.0):
    inputs = build._GuildInputs.__new__(build._GuildInputs)
    inputs.building_value = bv.parse_building_value(_csv(_row()), "sc")
    inputs.building_value_unavailable = ""
    inputs.other_building_levels = levels
    week = {
        "total_credit_points": total,
        "building_upgrades": [
            {"skill": "Milking", "building": "Guild Dairy Barn", "from_level": 0,
             "to_level": 1, "levels": 1, "total_cost": 2075, "points_gained": 100,
             "weeks_to_return": 51.875}],
        "shrine_upgrades": [
            {"shrine": "force", "name": "Shrine of Force", "from_level": 4,
             "next_level_cost": 3300, "points_gained_at_full_adoption": 0.95,
             "weeks_to_return": 3477.9}],
    }
    return build._buildings_artefact(_site(), inputs, week)


def test_artefact_applies_builders_hall_and_adds_utility_rows():
    doc = _utility_doc({BH: 8, TREASURY: 6})
    assert doc["schema_version"] == 3 and doc["gp_basis"] == "received"
    assert doc["gp_multiplier"] == pytest.approx(1.16)
    assert doc["builders_hall_level"] == 8
    by = {r["kind"]: r for r in doc["ranked"] if r["kind"] != "utility"}
    assert by["skilling"]["gain_gp_per_week"] == pytest.approx(
        100 / config.TRIAL_WEEKS_BETWEEN_DRAWS * 1.16)
    assert by["skilling"]["payback_weeks"] == pytest.approx(51.875 / 1.16)
    assert by["combat"]["gain_gp_per_week"] == pytest.approx(80 * 1.16)
    assert by["combat"]["payback_weeks"] == pytest.approx(50 / 1.16)
    combat_base = sum(trials_model.combat_points_for_credit(t, f)
                      for t, f in config.COMBAT_TRIALS_OBSERVED["sc"][0])
    weekly = 5000.0 + combat_base
    assert doc["weekly_base_gp"] == pytest.approx(weekly)
    bh = next(r for r in doc["ranked"] if r["key"] == BH)
    assert (bh["from_level"], bh["to_level"], bh["cost"]) == (8, 9, 11050)
    assert bh["gain_gp_per_week"] == pytest.approx(0.02 * weekly)
    assert bh["payback_weeks"] == pytest.approx(11050 / (0.02 * weekly))
    tr = doc["ranked"][-1]
    assert tr["key"] == TREASURY and tr["cost"] == 6050
    assert tr["payback_weeks"] is None and tr["rank"] is None
    assert tr["gain_gp_per_week"] is None
    assert tr["gain_tokens_per_member_week"] == pytest.approx(0.5 * 0.02 * weekly)
    gp_rows = [r for r in doc["ranked"] if r["payback_weeks"] is not None]
    assert [r["rank"] for r in gp_rows] == list(range(1, len(gp_rows) + 1))
    assert [r["payback_weeks"] for r in gp_rows] == sorted(r["payback_weeks"] for r in gp_rows)
    assert doc["skilling"]["upgrades"][0]["weeks_to_return"] == 51.875   # base, unscaled
    assert doc["skilling"]["gp_basis"] == doc["shrines"]["gp_basis"] == "base"


def test_artefact_without_combat_observation_is_a_labelled_lower_bound(monkeypatch):
    monkeypatch.setattr(config, "COMBAT_TRIALS_OBSERVED", {})
    doc = _utility_doc({BH: 8, TREASURY: 6})
    assert doc["weekly_base_gp"] == pytest.approx(5000.0)
    bh = next(r for r in doc["ranked"] if r["key"] == BH)
    assert "lower bound" in bh["confidence"]


def test_artefact_without_buildings_tab_has_no_utility_rows_and_says_so():
    doc = _utility_doc(None)
    assert doc["gp_basis"] == "base" and doc["gp_multiplier"] == 1.0
    assert doc["weekly_base_gp"] is None
    assert not [r for r in doc["ranked"] if r["kind"] == "utility"]
    assert any("not been observed" in n for n in doc["notes"])


def test_artefact_skips_a_utility_building_at_the_cap():
    doc = _utility_doc({BH: 20, TREASURY: 6})
    assert doc["gp_multiplier"] == pytest.approx(1.4)
    assert [r["key"] for r in doc["ranked"] if r["kind"] == "utility"] == [TREASURY]


def test_guild_spend_section_renders_every_kind():
    assert build._render_guild_spend_section(None) == ""
    out = build._render_guild_spend_section(_utility_doc({BH: 8, TREASURY: 6}))
    assert 'id="guild-spend-section"' in out
    for kind in ("combat", "skilling", "shrine", "utility"):
        assert f"<td>{kind}</td>" in out
    assert "Builder&#x27;s Hall" in out and "tokens, not GP" in out and "1.16" in out


def test_zero_gain_builders_hall_is_not_priced_and_treasury_stays_tokens(monkeypatch):
    monkeypatch.setattr(config, "COMBAT_TRIALS_OBSERVED", {})
    doc = _utility_doc({BH: 8, TREASURY: 6}, total=0.0)
    assert [r["key"] for r in doc["ranked"] if r["kind"] == "utility"] == [TREASURY]
    assert "Builder's Hall not priced: no weekly base GP this week." in doc["notes"]
    out = build._render_guild_spend_section(doc)
    assert "+0.0 tokens/member" in out and "tokens, not GP" in out


def _combat_doc(*rows):
    inputs = build._GuildInputs.__new__(build._GuildInputs)
    inputs.building_value = bv.parse_building_value(_csv(*rows), "sc")
    inputs.building_value_unavailable = ""
    return build._buildings_artefact(_site(), inputs, {})


def test_combat_row_without_cost_is_skipped_and_renders():
    doc = _combat_doc(_row(), _row(**{"Upgrade": "Gym", "Hrid": "/guild_buildings/gym",
                                      "GP Cost": "", "Rank": "2"}))
    assert [r["name"] for r in doc["ranked"]] == ["Dojo"]
    build._render_guild_spend_section(doc)   # must not raise


def test_combat_row_without_payback_is_listed_as_rejected():
    doc = _combat_doc(_row(), _row(**{"Upgrade": "Gym", "Hrid": "/guild_buildings/gym",
                                      "Payback Weeks": "", "Verdict": "negative",
                                      "Rank": "2"}))
    out = build._render_guild_spend_section(doc)
    assert "Checked and rejected (combat): Gym (negative)" in out
    assert "Skilling and shrine upgrades with no payback" in out


def test_observed_tab_missing_builders_hall_says_so_and_stays_base():
    doc = _utility_doc({TREASURY: 6})
    assert doc["gp_basis"] == "base" and doc["builders_hall_level"] is None
    assert any("Builder's Hall level missing from the Buildings tab" in n
               for n in doc["notes"])
    assert any("observed week" in n for n in doc["notes"])


def test_multi_level_skilling_row_carries_its_average_rate():
    inputs = build._GuildInputs.__new__(build._GuildInputs)
    inputs.building_value = None
    inputs.building_value_unavailable = "never written"
    doc = build._buildings_artefact(_site(), inputs, {"building_upgrades": [
        {"skill": "Cooking", "building": "Guild Kitchen", "from_level": 4,
         "to_level": 6, "levels": 2, "total_cost": 3900, "points_gained": 100,
         "weeks_to_return": 97.5}]})
    row = doc["ranked"][0]
    assert (row["from_level"], row["to_level"], row["cost"]) == (4, 6, 3900)
    per_level = 100 / config.TRIAL_WEEKS_BETWEEN_DRAWS / 2
    assert row["recommendation"] == f"2 levels, avg +{per_level:.1f} GP/week each"
