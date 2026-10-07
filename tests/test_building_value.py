"""The combat building-value tab reader and the buildings.json artefact."""

import csv
import io

import pytest

from src import build, config
from src import building_value as bv
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
             "to_level": 3, "total_cost": 2075, "points_gained": 100,
             "weeks_to_return": 51.875},
            {"skill": "Cooking", "building": "Guild Kitchen", "from_level": 20,
             "to_level": None, "total_cost": None, "points_gained": 0,
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
         "to_level": 3, "total_cost": 2075, "points_gained": 100,
         "weeks_to_return": 51.875}]})
    assert doc["combat"]["available"] is False
    assert doc["combat"]["unavailable"] == "never written"
    assert [r["kind"] for r in doc["ranked"]] == ["skilling"]
