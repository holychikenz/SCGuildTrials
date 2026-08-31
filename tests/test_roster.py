"""Unit tests for src/roster.py. No network access.

The inline fixtures replicate the ROSTER tab's shape, which is a third shape
again from the two already covered here: one clean, fully-quoted header row of
78 named columns (no merged junk, no group rows), one row per member, addressed
BY NAME rather than by position.

The hazards these pin, in order of how quietly they would fail:
  - the tool block's column order varies upstream, so a positional read would
    score the wrong tool without erroring;
  - blank and zero mean different things on this tab and must not collapse;
  - "Bell Farming" is the alchemy column and "C.Smithing" is cheesesmithing.
"""

import pytest

from src import config, roster
from src.reader import SheetStructureError

# The live column set, in the live order (verified 2026-08-31). Columns the
# parser never reads are present here on purpose: the guard must tolerate them.
_LIVE_HEADER = [
    "name", "characterId", "guildId", "guildName", "guildRole", "capturedAt",
    "revision", "setsComplete", "set_beginner", "set_novice", "set_adept",
    "set_veteran", "set_elite", "set_champion",
    "milking", "foraging", "woodcutting", "cheesesmithing", "crafting",
    "tailoring", "cooking", "brewing", "alchemy", "enhancing",
    "stamina", "intelligence", "attack", "defense", "melee", "ranged", "magic",
    "house_dairy_barn", "house_garden", "house_log_shed", "house_forge",
    "house_workshop", "house_sewing_parlor", "house_kitchen", "house_brewery",
    "house_laboratory", "house_observatory", "house_dining_room",
    "house_library", "house_dojo", "house_armory", "house_gym",
    "house_archery_range", "house_mystical_study",
    "shrine_force_combat", "shrine_force_skilling",
    "shrine_tempo_combat", "shrine_tempo_skilling",
    "shrine_spirit_combat", "shrine_spirit_skilling",
    "shrine_rarity_combat", "shrine_rarity_skilling",
    "shrine_scholar_combat", "shrine_scholar_skilling",
    "tool_alchemy", "tool_alchemyEnh",
    "tool_brewing", "tool_brewingEnh",
    "tool_cheesesmithing", "tool_cheesesmithingEnh",
    "tool_cooking", "tool_cookingEnh",
    "tool_crafting", "tool_craftingEnh",
    "tool_enhancing", "tool_enhancingEnh",
    "tool_foraging", "tool_foragingEnh",
    "tool_milking", "tool_milkingEnh",
    "tool_tailoring", "tool_tailoringEnh",
    "tool_woodcutting", "tool_woodcuttingEnh",
]

# Sensible defaults for one member, by column name. Anything unset is blank.
_DEFAULTS = {
    "name": "Yedic",
    "characterId": "14630",
    "guildId": "4",
    "guildName": "Survey Corps",
    "guildRole": "general",
    "capturedAt": "2026-08-28T11:19:06.697Z",
    "revision": "1",
    "milking": "125", "foraging": "125", "woodcutting": "119",
    "cheesesmithing": "126", "crafting": "125", "tailoring": "121",
    "cooking": "125", "brewing": "122", "alchemy": "116", "enhancing": "110",
    "house_dairy_barn": "6", "house_garden": "6", "house_log_shed": "6",
    "house_forge": "6", "house_workshop": "6", "house_sewing_parlor": "6",
    "house_kitchen": "6", "house_brewery": "6", "house_laboratory": "6",
    "house_observatory": "6",
    "shrine_force_skilling": "4", "shrine_tempo_skilling": "3",
    "shrine_spirit_skilling": "2", "shrine_rarity_skilling": "0",
    "shrine_scholar_skilling": "1",
    "tool_milking": "Celestial Brush", "tool_milkingEnh": "10",
    "tool_foraging": "Holy Shears", "tool_foragingEnh": "7",
    "tool_woodcutting": "Holy Hatchet", "tool_woodcuttingEnh": "5",
    "tool_cheesesmithing": "Holy Hammer", "tool_cheesesmithingEnh": "5",
    "tool_crafting": "Holy Chisel", "tool_craftingEnh": "5",
    "tool_tailoring": "Holy Needle", "tool_tailoringEnh": "6",
    "tool_cooking": "Holy Spatula", "tool_cookingEnh": "7",
    "tool_brewing": "Holy Pot", "tool_brewingEnh": "5",
    "tool_alchemy": "Rainbow Alembic", "tool_alchemyEnh": "4",
    "tool_enhancing": "Celestial Enhancer", "tool_enhancingEnh": "9",
}


def _quote_row(cells):
    """Join cells as a fully-quoted CSV line, the way gviz emits them."""
    return ",".join('"' + str(c).replace('"', '""') + '"' for c in cells)


def _roster_csv(rows, header=None):
    """Build roster CSV text from ``[{column: value}, ...]``."""
    header = list(header if header is not None else _LIVE_HEADER)
    lines = [_quote_row(header)]
    for row in rows:
        values = dict(_DEFAULTS)
        values.update(row)
        lines.append(_quote_row([values.get(name, "") for name in header]))
    return "\n".join(lines) + "\n"


def _one(**overrides):
    """Parse a single-member roster and return its RosterRow."""
    parsed = roster.parse(_roster_csv([overrides]))
    assert len(parsed) == 1
    return parsed[0]


# --- the structure guard ----------------------------------------------------
def test_header_guard_accepts_the_live_column_set():
    index = roster._validate_header(_LIVE_HEADER)
    assert index["name"] == 0
    assert index["tool_woodcuttingEnh"] == len(_LIVE_HEADER) - 1


def test_header_guard_rejects_a_renamed_column():
    header = [
        "tool_milking_speed" if c == "tool_milking" else c for c in _LIVE_HEADER
    ]
    with pytest.raises(SheetStructureError) as exc:
        roster._validate_header(header)
    assert "tool_milking" in str(exc.value)


def test_header_guard_lists_every_missing_column():
    dropped = {"alchemy", "house_laboratory", "shrine_tempo_skilling"}
    header = [c for c in _LIVE_HEADER if c not in dropped]
    with pytest.raises(SheetStructureError) as exc:
        roster._validate_header(header)
    message = str(exc.value)
    for name in dropped:
        assert name in message


def test_header_guard_tolerates_extra_columns():
    # The upstream module's `stableGear` toggle adds fourteen columns. Nobody in
    # this repository controls that toggle, so it must not break the build.
    extra = [
        "gear_pouch", "gear_pouchEnh", "gear_trinket", "gear_trinketEnh",
        "gear_neck", "gear_neckEnh", "gear_ring", "gear_ringEnh",
        "gear_earrings", "gear_earringsEnh", "gear_back", "gear_backEnh",
        "gear_feet", "gear_feetEnh",
    ]
    header = _LIVE_HEADER + extra
    parsed = roster.parse(_roster_csv([{}], header=header))
    assert parsed[0].levels["Milking"] == 125


def test_empty_csv_is_a_structure_error():
    with pytest.raises(SheetStructureError):
        roster.parse("")


# --- reading by name, not by position ---------------------------------------
def test_columns_are_read_by_name_not_position():
    """The ResearchPack's named hazard: the tool block's order VARIES upstream.

    itemLocationDetailMap carries no sortIndex, so the twenty tool columns come
    out alphabetical when client data was captured and in skill order from the
    module's fallback. A positional reader would silently score a Celestial
    Brush as a Holy Enhancer; a name-addressed one parses identically.
    """
    tool_start = _LIVE_HEADER.index("tool_alchemy")
    head, tools = _LIVE_HEADER[:tool_start], _LIVE_HEADER[tool_start:]
    # Reverse the whole tool block, keeping each name paired with its data.
    shuffled = head + list(reversed(tools))

    straight = roster.parse(_roster_csv([{}]))[0]
    crooked = roster.parse(_roster_csv([{}], header=shuffled))[0]

    assert crooked.tools == straight.tools
    assert crooked.tool_enh == straight.tool_enh
    assert crooked.tools["Milking"] == "Celestial Brush"
    assert crooked.tool_enh["Milking"] == 10


def test_singleton_columns_are_read_by_name_too():
    reordered = ["capturedAt", "revision", "characterId"] + [
        c for c in _LIVE_HEADER if c not in {"capturedAt", "revision", "characterId"}
    ]
    row = roster.parse(_roster_csv([{}], header=reordered))[0]
    assert row.character_id == "14630"
    assert row.captured_at == "2026-08-28T11:19:06.697Z"
    assert row.revision == "1"


# --- blank is not zero ------------------------------------------------------
def test_blank_and_zero_are_distinguished():
    """The endpoint preserves the difference and so must the parser.

    ``0`` is a catalogue item the member never acquired; blank is a value
    withheld (hideWearableItems) or unknown. Collapsing the two would price nine
    SC members' HIDDEN gear as NO gear.
    """
    row = _one(
        milking="0", foraging="",
        house_dairy_barn="0", house_garden="",
        tool_milkingEnh="0", tool_foragingEnh="",
        tool_foraging="",
        shrine_force_skilling="0", shrine_tempo_skilling="",
    )
    assert row.levels["Milking"] == 0
    assert row.levels["Foraging"] is None
    assert row.houses["Milking"] == 0
    assert row.houses["Foraging"] is None
    assert row.tool_enh["Milking"] == 0
    assert row.tool_enh["Foraging"] is None
    assert row.tools["Foraging"] is None
    assert row.shrines["force"] == 0
    assert row.shrines["tempo"] is None


def test_gear_hider_leaves_every_tool_column_blank_but_keeps_the_rest():
    blank_tools = {}
    for skill in config.SKILLS:
        _lv, _house, tool = config.ROSTER_COLUMNS[skill]
        blank_tools[tool] = ""
        blank_tools[tool + config.ROSTER_TOOL_ENH_SUFFIX] = ""
    row = _one(**blank_tools)
    assert set(row.tools.values()) == {None}
    assert set(row.tool_enh.values()) == {None}
    assert row.levels["Milking"] == 125
    assert row.houses["Enhancing"] == 6
    assert row.shrines["force"] == 4


def test_non_numeric_level_raises_rather_than_becoming_none():
    """reader._to_int's tolerance is right for a HAND-maintained tab, not here."""
    with pytest.raises(SheetStructureError) as exc:
        _one(milking="one hundred")
    assert "milking" in str(exc.value)
    assert "Yedic" in str(exc.value)


def test_non_numeric_enhancement_raises():
    with pytest.raises(SheetStructureError):
        _one(tool_milkingEnh="ten")


def test_a_signed_numeral_still_parses():
    """int() accepts a leading sign, and that is the right tolerance: "+10" is
    unambiguously ten, not a format change."""
    assert _one(tool_milkingEnh="+10").tool_enh["Milking"] == 10


# --- the two column-name traps ----------------------------------------------
def test_alchemy_column_maps_to_bell_farming():
    row = _one(alchemy="99", house_laboratory="3", tool_alchemy="Azure Alembic")
    assert row.levels["Bell Farming"] == 99
    assert row.houses["Bell Farming"] == 3
    assert row.tools["Bell Farming"] == "Azure Alembic"
    assert "Alchemy" not in row.levels


def test_cheesesmithing_column_maps_to_c_smithing():
    row = _one(cheesesmithing="88", house_forge="2", tool_cheesesmithing="Holy Hammer")
    assert row.levels["C.Smithing"] == 88
    assert row.houses["C.Smithing"] == 2
    assert row.tools["C.Smithing"] == "Holy Hammer"


def test_every_skill_is_present_in_every_map():
    row = _one()
    for mapping in (row.levels, row.houses, row.tools, row.tool_enh):
        assert set(mapping) == set(config.SKILLS)


def test_house_map_pairs_each_skill_with_its_own_room():
    # Distinct house levels per skill, so a mis-paired room shows up.
    row = _one(**{
        "house_dairy_barn": "1", "house_garden": "2", "house_log_shed": "3",
        "house_forge": "4", "house_workshop": "5", "house_sewing_parlor": "6",
        "house_kitchen": "7", "house_brewery": "8", "house_laboratory": "0",
        "house_observatory": "5",
    })
    assert row.houses == {
        "Milking": 1, "Foraging": 2, "Woodcutting": 3, "C.Smithing": 4,
        "Crafting": 5, "Tailoring": 6, "Cooking": 7, "Brewing": 8,
        "Bell Farming": 0, "Enhancing": 5,
    }


# --- shrines ----------------------------------------------------------------
def test_all_five_skilling_shrines_are_parsed():
    row = _one()
    assert row.shrines == {
        "force": 4, "tempo": 3, "spirit": 2, "rarity": 0, "scholar": 1,
    }
    assert set(row.shrines) == set(config.GUILD_SHRINE_SKILLING_BUFFS)


def test_combat_shrine_columns_are_ignored():
    row = _one(shrine_force_combat="20", shrine_tempo_combat="20")
    assert row.shrines["force"] == 4
    assert row.shrines["tempo"] == 3


# --- row termination --------------------------------------------------------
def test_rows_stop_at_the_first_blank_name():
    text = _roster_csv([{"name": "A"}, {"name": "B"}, {"name": ""}, {"name": "C"}])
    parsed = roster.parse(text)
    assert [r.name for r in parsed] == ["A", "B"]


def test_short_rows_read_as_blank_rather_than_raising():
    text = _roster_csv([{}])
    lines = text.splitlines()
    lines[1] = ",".join(lines[1].split(",")[:20])  # truncate the data row
    parsed = roster.parse("\n".join(lines) + "\n")
    assert parsed[0].name == "Yedic"
    assert parsed[0].tools["Milking"] is None


# --- the fetch path ---------------------------------------------------------
def test_gviz_no_header_collapse_is_not_appended(monkeypatch):
    """&headers=0 blanks the label of every numeric column on this tab."""
    seen = {}

    def fake_fetch(tab_name):
        seen["tab"] = tab_name
        return _roster_csv([{}])

    monkeypatch.setattr(roster, "fetch_tab_csv", fake_fetch)
    rows = roster.scrape_roster_tab("SC Roster")
    assert seen["tab"] == "SC Roster"  # no query-string suffix smuggled in
    assert config.GVIZ_NO_HEADER_COLLAPSE not in seen["tab"]
    assert len(rows) == 1


def test_roster_tabs_are_configured_for_both_guilds():
    assert config.ROSTER_TABS == {"sc": "SC Roster", "li": "LI Roster"}
    assert set(config.ROSTER_TABS) == set(config.TABS)


# ===========================================================================
# R2 — the join, the merge, and the rollback's proof
# ===========================================================================
import copy  # noqa: E402
import json  # noqa: E402

from src import build as build_model, processor, trials  # noqa: E402
from src.reader import MemberRow, SkillEntry  # noqa: E402
from tests.golden_fixture import (  # noqa: E402
    GOLDEN_CAP,
    GOLDEN_DRAW,
    GOLDEN_SEED,
    GOLDEN_STRATEGY,
    golden_members,
)

_GOLDEN_PATH = "tests/golden/week_pre_roster.json"


def _member(name, level=100, tool=False, top=False, bot=False, house=4):
    """A manual-tab member with the same value in every skill."""
    return MemberRow(
        name=name, main_classes="", flex="", flex_levels=[],
        skills={
            s: SkillEntry(level=level, tool=tool, top=top, bot=bot, house=house)
            for s in config.SKILLS
        },
    )


# --- the golden: the rollback's proof ---------------------------------------
def test_roster_disabled_reproduces_the_golden_week(monkeypatch):
    """ROSTER_SOURCE_ENABLED = False must reproduce the pre-roster week EXACTLY.

    Compared with ``==`` against a golden generated from the pre-change commit
    (265326b) — not ``approx``. _prepare_member's docstring records a live case
    where a one-ULP change reshuffled every SC party for no gain, so
    ULP-exactness IS the property under test.
    """
    monkeypatch.setattr(config, "ROSTER_SOURCE_ENABLED", False)
    week = trials.run_week(
        golden_members(),
        skills=list(GOLDEN_DRAW),
        seed=GOLDEN_SEED,
        cap=GOLDEN_CAP,
        strategy=GOLDEN_STRATEGY,
    )
    got = week.to_dict()
    got.pop("generated_at", None)
    got.pop("week_date", None)

    # R4 added four ADDITIVE provenance keys to every roster entry, so the
    # golden — generated before they existed — is compared after they are
    # stripped. They are not simply discarded: each is asserted to carry the
    # pre-roster answer first, which IS the R4 property ("renders manual for
    # everything while the switch is off"). What the golden pins is the RACE,
    # and the race must still match bit for bit.
    for trial in got["trials"]:
        for entry in trial["roster"]:
            assert entry.pop("source") == "manual"
            assert entry.pop("tool_source") == "manual"
            assert entry.pop("tool_item") is None
            assert entry.pop("tool_enhance") is None
    got.pop("provenance", None)

    with open(_GOLDEN_PATH, encoding="utf-8") as fh:
        expected = json.load(fh)
    assert got == expected


def test_data_json_is_byte_identical_with_roster_off():
    """The optional roster fields must not emit null keys into data.json."""
    payload = processor.process([_member("solo")])
    member = payload["members"][0]
    assert set(member) == {"name", "main_classes", "flex", "flex_levels", "skills"}
    entry = member["skills"]["Milking"]
    assert set(entry) == {"level", "tool", "top", "bot", "house"}
    assert "tool_item" not in json.dumps(payload)


def test_serialised_roster_fields_appear_once_they_are_set():
    m = _member("solo")
    m.character_id = "1"
    m.shrine_levels = {"force": 3}
    m.skills["Milking"].tool_item = "Celestial Brush"
    d = processor.process([m])["members"][0]
    assert d["character_id"] == "1"
    assert d["shrine_levels"] == {"force": 3}
    assert d["skills"]["Milking"]["tool_item"] == "Celestial Brush"
    # Still per FIELD: the enhancement was never set, so it is still absent.
    assert "tool_enhance" not in d["skills"]["Milking"]
    assert "captured_at" not in d


def _stub_fetch_guild(monkeypatch, calls):
    """Stub every network call _fetch_guild makes except the roster's."""
    from src import scraper

    gd = scraper.GuildData(
        tab="LI Member Data", fetched_at="t", member_count=1,
        members=[_member("Yedic")],
    )
    monkeypatch.setattr(build_model, "scrape_member_tab", lambda tab: gd)
    monkeypatch.setattr(
        build_model.signup_model, "fetch_signup_csv", lambda tab: "csv"
    )
    monkeypatch.setattr(
        build_model.draw_model, "trial_columns", lambda csv, tab: ["Milking"]
    )
    monkeypatch.setattr(
        build_model.signup_model, "parse_signup", lambda csv, tab_label=None: {}
    )

    def fake_scrape_roster(tab):
        calls.append(tab)
        return roster.parse(_roster_csv([{"name": "Yedic"}]))

    monkeypatch.setattr(build_model.roster_model, "scrape_roster_tab", fake_scrape_roster)
    return gd


def test_roster_disabled_makes_no_second_http_request(monkeypatch):
    """The gating is at the FETCH, so a broken roster deployment cannot bite."""
    calls = []
    _stub_fetch_guild(monkeypatch, calls)
    monkeypatch.setattr(config, "ROSTER_SOURCE_ENABLED", False)
    site = [s for s in build_model.GUILD_SITES if s.key == "li"][0]
    inputs = build_model._fetch_guild(
        site, build_model.draw_model.TrialDraw(skills=["Milking"], date="x")
    )
    assert calls == []
    assert inputs.roster_provenance is None


def test_roster_enabled_fetches_the_roster_tab_once(monkeypatch):
    calls = []
    _stub_fetch_guild(monkeypatch, calls)
    monkeypatch.setattr(config, "ROSTER_SOURCE_ENABLED", True)
    site = [s for s in build_model.GUILD_SITES if s.key == "li"][0]
    inputs = build_model._fetch_guild(
        site, build_model.draw_model.TrialDraw(skills=["Milking"], date="x")
    )
    assert calls == ["LI Roster"]
    assert inputs.roster_provenance.roster_backed == 1


def test_a_broken_roster_header_degrades_rather_than_stopping_the_build(monkeypatch):
    """SC is required=True: an uncaught raise here kills every page of both guilds."""
    calls = []
    _stub_fetch_guild(monkeypatch, calls)

    def boom(tab):
        raise SheetStructureError("column 'milking' is missing")

    monkeypatch.setattr(build_model.roster_model, "scrape_roster_tab", boom)
    monkeypatch.setattr(config, "ROSTER_SOURCE_ENABLED", True)
    site = [s for s in build_model.GUILD_SITES if s.key == "li"][0]
    inputs = build_model._fetch_guild(
        site, build_model.draw_model.TrialDraw(skills=["Milking"], date="x")
    )
    assert "could not be read" in inputs.roster_unavailable
    assert inputs.roster_provenance is None
    assert [m.name for m in inputs.members] == ["Yedic"]


# --- the join ---------------------------------------------------------------
def test_join_is_case_insensitive():
    members = [_member("dome"), _member("VIadd"), _member("FeaI")]
    rows = roster.parse(
        _roster_csv([{"name": "Dome"}, {"name": "Viadd"}, {"name": "Feai"}])
    )
    report = roster.join(members, rows)
    assert len(report.matched) == 3
    assert len(report.normalized_matches) == 3
    assert report.unmatched_members == []
    assert report.unmatched_roster == []


def test_exact_match_wins_over_the_normalised_one():
    members = [_member("Dome")]
    rows = roster.parse(_roster_csv([{"name": "dome"}, {"name": "Dome"}]))
    report = roster.join(members, rows)
    assert report.matched[0].character_id == "14630"
    assert report.normalized_matches == []


def test_join_reports_unmatched_on_both_sides():
    members = [_member("Yedic"), _member("OTZ")]
    rows = roster.parse(_roster_csv([{"name": "Yedic"}, {"name": "IronPugs"}]))
    report = roster.join(members, rows)
    assert report.unmatched_members == ["OTZ"]
    assert report.unmatched_roster == ["IronPugs"]
    assert [r.name for r in report.roster_only] == ["IronPugs"]


def test_ambiguous_normalised_name_joins_to_nobody():
    """signup.py:1253-1259's rule, verbatim: an ambiguous key matches nobody."""
    members = [_member("bob"), _member("BOB")]
    rows = roster.parse(_roster_csv([{"name": "Bob"}]))
    report = roster.join(members, rows)
    assert report.matched == {}
    assert sorted(report.ambiguous) == ["BOB", "bob"]
    assert report.unmatched_roster == ["Bob"]


def test_two_roster_rows_sharing_a_normalised_name_match_nobody():
    members = [_member("bob")]
    rows = roster.parse(_roster_csv([{"name": "Bob"}, {"name": "BOB"}]))
    report = roster.join(members, rows)
    assert report.matched == {}
    assert report.ambiguous == ["bob"]


# --- the merge --------------------------------------------------------------
def _merged(member_kwargs=None, roster_overrides=None, name="Yedic"):
    members = [_member(name, **(member_kwargs or {}))]
    rows = roster.parse(_roster_csv([dict(roster_overrides or {}, name=name)]))
    report = roster.join(members, rows)
    merged, prov = roster.merge(members, report, "sc")
    return members, merged, prov


def test_merge_does_not_mutate_the_input_members():
    """index.html must keep mirroring the officers' own tab, stale cells and all."""
    members, merged, _prov = _merged({"level": 100, "house": 4})
    before = copy.deepcopy(members)
    assert members == before
    assert members[0].skills["Milking"].level == 100
    assert merged[0].skills["Milking"].level == 125  # the roster's value
    assert members[0].provenance == {}


def test_roster_levels_and_houses_win():
    _m, merged, prov = _merged({"level": 100, "house": 4})
    assert merged[0].skills["Milking"].level == 125
    assert merged[0].skills["Milking"].house == 6
    assert merged[0].provenance["Milking.level"] == roster.ROSTER
    assert merged[0].provenance["member"] == roster.ROSTER
    assert prov.roster_backed == 1


def test_switching_levels_off_keeps_the_manual_level(monkeypatch):
    monkeypatch.setattr(config, "ROSTER_USE_LEVELS", False)
    _m, merged, _prov = _merged({"level": 100})
    assert merged[0].skills["Milking"].level == 100
    assert merged[0].provenance["Milking.level"] == roster.MANUAL
    assert merged[0].skills["Milking"].house == 6  # houses still roster-backed


def test_gear_hider_keeps_roster_levels_and_manual_tools():
    """THE per-field test. Nine SC and seven LI members are exactly this case."""
    blank_tools = {}
    for skill in config.SKILLS:
        _lv, _house, tool = config.ROSTER_COLUMNS[skill]
        blank_tools[tool] = ""
        blank_tools[tool + config.ROSTER_TOOL_ENH_SUFFIX] = ""
    _m, merged, prov = _merged({"level": 100, "tool": True}, blank_tools)
    entry = merged[0].skills["Milking"]
    assert entry.level == 125            # roster
    assert entry.house == 6              # roster
    assert entry.tool is True            # the manual checkbox
    assert entry.tool_item is None       # the roster said nothing
    assert merged[0].provenance["Milking.tool"] == roster.MANUAL
    assert merged[0].provenance["Milking.level"] == roster.ROSTER
    assert prov.gear_hidden == ["Yedic"]


def test_roster_tool_item_and_enhancement_are_carried():
    _m, merged, _prov = _merged()
    entry = merged[0].skills["Milking"]
    assert entry.tool_item == "Celestial Brush"
    assert entry.tool_enhance == 10


def test_member_missing_from_the_roster_is_fully_manual(monkeypatch):
    # The floor has its own two tests; a two-member fixture would trip it.
    monkeypatch.setattr(config, "ROSTER_MIN_JOIN_RATE", 0.0)
    members = [_member("Yedic", level=100), _member("OTZ", level=99)]
    rows = roster.parse(_roster_csv([{"name": "Yedic"}]))
    merged, prov = roster.merge(members, roster.join(members, rows), "li")
    otz = merged[1]
    assert otz.skills["Milking"].level == 99
    assert otz.provenance["member"] == roster.MANUAL
    assert otz.character_id is None
    assert otz.shrine_levels == {}
    assert prov.manual_backed == 1 and prov.roster_backed == 1


def test_top_and_bot_are_always_the_manual_tabs():
    """The roster does not carry body or legs and never will (§11.3)."""
    _m, merged, _prov = _merged({"top": True, "bot": True})
    assert merged[0].skills["Milking"].top is True
    assert merged[0].skills["Milking"].bot is True


def test_shrine_levels_are_carried_as_levels_not_bonuses():
    _m, merged, _prov = _merged()
    assert merged[0].shrine_levels == {
        "force": 4, "tempo": 3, "spirit": 2, "rarity": 0, "scholar": 1,
    }


def test_blank_shrine_column_is_absent_rather_than_zero():
    _m, merged, _prov = _merged(roster_overrides={"shrine_tempo_skilling": ""})
    assert "tempo" not in merged[0].shrine_levels
    assert merged[0].shrine_levels["force"] == 4


def test_switching_shrines_off_carries_no_levels(monkeypatch):
    monkeypatch.setattr(config, "ROSTER_USE_SHRINES", False)
    _m, merged, _prov = _merged()
    assert merged[0].shrine_levels == {}


def test_provenance_counts_sum_to_member_count_times_skill_count(monkeypatch):
    monkeypatch.setattr(config, "ROSTER_MIN_JOIN_RATE", 0.0)
    members = [_member("Yedic"), _member("OTZ")]
    rows = roster.parse(_roster_csv([{"name": "Yedic"}]))
    _merged_rows, prov = roster.merge(members, roster.join(members, rows), "sc")
    for field_name in ("level", "house", "tool"):
        assert sum(prov.fields[field_name].values()) == 2 * len(config.SKILLS)


def test_join_below_min_rate_refuses_the_roster_for_that_guild():
    """A wholesale mis-join would silently reprice a whole guild."""
    members = [_member(f"m{i}") for i in range(10)]
    rows = roster.parse(_roster_csv([{"name": "m0"}]))
    merged, prov = roster.merge(members, roster.join(members, rows), "sc")
    assert prov.refused
    assert "10%" in prov.refused
    assert all(m.provenance == {} for m in merged)
    assert merged[0].skills["Milking"].level == 100  # untouched, i.e. today
    assert prov.admitted == 0


def test_a_join_at_the_floor_is_accepted():
    members = [_member(f"m{i}") for i in range(10)]
    rows = roster.parse(_roster_csv([{"name": f"m{i}"} for i in range(9)]))
    _merged_rows, prov = roster.merge(members, roster.join(members, rows), "sc")
    assert prov.refused == ""
    assert prov.roster_backed == 9


# --- roster-only members are ADMITTED (§5.6, revised) -----------------------
_ROSTER_ONLY = [
    {"name": "IronPugs", "characterId": "280884", "cheesesmithing": "93"},
    {"name": "U3", "characterId": "281111", "cheesesmithing": "102"},
    {"name": "auuughhh", "characterId": "117231", "cheesesmithing": "106"},
    {"name": "yiyaa", "characterId": "287196", "cheesesmithing": "105",
     "shrine_force_skilling": "2", "shrine_tempo_skilling": "3",
     "tool_enhancing": "Holy Enhancer", "tool_enhancingEnh": "5"},
    {"name": "yiyya", "characterId": "287200", "cheesesmithing": "107",
     "shrine_force_skilling": "2", "shrine_tempo_skilling": "2",
     "tool_enhancing": "Holy Enhancer", "tool_enhancingEnh": "6"},
]


def _li_shaped():
    """One manual member plus the five live LI roster-only names."""
    members = [_member("Felisie")]
    rows = roster.parse(_roster_csv([{"name": "Felisie"}] + _ROSTER_ONLY))
    return members, rows


def test_roster_only_members_are_admitted_by_default():
    members, rows = _li_shaped()
    merged, prov = roster.merge(members, roster.join(members, rows), "li")
    assert prov.admitted == 5
    assert prov.admitted_names == ["IronPugs", "U3", "auuughhh", "yiyaa", "yiyya"]
    assert [m.name for m in merged[1:]] == prov.admitted_names
    assert len({m.character_id for m in merged[1:]}) == 5
    assert prov.reported_not_seated == []


def test_the_yiyaa_yiyya_pair_is_two_members_not_one():
    """The rename hazard §5.6 originally refused them for. It is false.

    Distinct characterIds, different shrines and different tool enhancement —
    and apps-script/profiles/Code.gs upserts on characterId, so two rows can
    only ever mean two characters.
    """
    members, rows = _li_shaped()
    merged, _prov = roster.merge(members, roster.join(members, rows), "li")
    pair = [m for m in merged if m.name in ("yiyaa", "yiyya")]
    assert len(pair) == 2
    assert {m.character_id for m in pair} == {"287196", "287200"}
    assert pair[0].shrine_levels != pair[1].shrine_levels
    assert (
        pair[0].skills["Enhancing"].tool_enhance
        != pair[1].skills["Enhancing"].tool_enhance
    )


def test_an_admitted_member_has_no_top_or_bot():
    """Necessarily False: no manual row, and the roster omits body and legs."""
    members, rows = _li_shaped()
    merged, _prov = roster.merge(members, roster.join(members, rows), "li")
    admitted = merged[1]
    for skill in config.SKILLS:
        assert admitted.skills[skill].top is False
        assert admitted.skills[skill].bot is False
    assert admitted.provenance["member"] == roster.ROSTER_ONLY
    assert admitted.main_classes == "" and admitted.flex == ""


def test_an_admitted_member_is_absent_from_the_unmerged_register_list():
    members, rows = _li_shaped()
    merged, _prov = roster.merge(members, roster.join(members, rows), "li")
    register = processor.process(members)
    assert register["member_count"] == 1
    assert [m["name"] for m in register["members"]] == ["Felisie"]
    assert len(merged) == 6


def test_admitting_is_deterministic_in_roster_row_order():
    members, rows = _li_shaped()
    a, _ = roster.merge(members, roster.join(members, rows), "li")
    b, _ = roster.merge(members, roster.join(members, rows), "li")
    assert [m.name for m in a] == [m.name for m in b]
    assert [m.name for m in a][1:] == [r["name"] for r in _ROSTER_ONLY]


def test_admitted_members_carry_roster_levels_and_shrines():
    members, rows = _li_shaped()
    merged, _prov = roster.merge(members, roster.join(members, rows), "li")
    yiyaa = [m for m in merged if m.name == "yiyaa"][0]
    assert yiyaa.skills["C.Smithing"].level == 105
    assert yiyaa.shrine_levels["force"] == 2
    assert yiyaa.provenance["C.Smithing.level"] == roster.ROSTER


def test_roster_only_member_is_reported_but_not_seated_when_the_switch_is_off(
    monkeypatch,
):
    monkeypatch.setattr(config, "ROSTER_ADMITS_NEW_MEMBERS", False)
    members, rows = _li_shaped()
    merged, prov = roster.merge(members, roster.join(members, rows), "li")
    assert len(merged) == 1
    assert prov.admitted == 0
    assert prov.reported_not_seated == [r["name"] for r in _ROSTER_ONLY]


def test_a_member_on_both_tabs_is_never_admitted_twice():
    members, rows = _li_shaped()
    merged, prov = roster.merge(members, roster.join(members, rows), "li")
    assert [m.name for m in merged].count("Felisie") == 1
    assert prov.member_count == len(merged) == 6


# ===========================================================================
# R4 — provenance on the pages and in the JSON
# ===========================================================================
def _prov_on(**overrides):
    base = {
        "enabled": True, "source": "roster tab", "roster_backed": 98,
        "manual_backed": 9, "admitted": 5,
        "admitted_names": ["IronPugs", "U3", "auuughhh", "yiyaa", "yiyya"],
        "reported_not_seated": [], "captured_at": "2026-08-28T11:19:06.697Z",
        "age_days": 3, "stale": False, "gear_hidden": 9, "unknown_tools": 0,
        "unknown_tool_items": {}, "blank_enhancements": 0,
        "unmatched_roster": [], "unmatched_members": [], "normalized_matches": [],
        "ambiguous": [], "refused": "", "unavailable": "",
    }
    base.update(overrides)
    return base


def test_provenance_strip_says_manual_when_the_roster_is_off():
    """Nothing may ship with better numbers than the page admits to."""
    html_ = build_model._render_provenance_strip(
        build_model._provenance_placeholder(107)
    )
    assert "107" in html_
    assert "hand-maintained member tab" in html_
    assert "ROSTER_SOURCE_ENABLED" in html_
    assert "roster-backed" not in html_


def test_provenance_strip_reports_the_counts_when_the_roster_is_on():
    html_ = build_model._render_provenance_strip(_prov_on())
    assert "roster-backed" in html_
    assert "2026-08-28" in html_
    assert "3 days ago" in html_
    assert "9 hide their gear" in html_
    assert "seated from the roster" in html_
    assert "yiyaa" in html_


def test_provenance_strip_is_outlined_when_the_capture_is_stale():
    fresh = build_model._render_provenance_strip(_prov_on())
    stale = build_model._render_provenance_strip(_prov_on(age_days=40, stale=True))
    assert 'class="prov"' in fresh
    assert 'class="prov stale"' in stale
    assert "older than" in stale


def test_provenance_strip_says_so_when_the_roster_was_refused():
    html_ = build_model._render_provenance_strip(
        _prov_on(refused="only 3 of 107 members (3%) joined a roster row")
    )
    assert "refused" in html_
    assert "3 of 107" in html_


def test_capture_age_is_none_rather_than_fatal_on_an_unparseable_stamp():
    assert build_model._capture_age_days("not a date") is None
    assert build_model._capture_age_days("") is None
    assert build_model._capture_age_days("2026-08-28T11:19:06.697Z") is not None


def test_source_mark_is_filled_for_roster_and_hollow_for_manual():
    assert "src on" in build_model._source_mark("roster")
    assert "src off" in build_model._source_mark("manual")
    assert "src only" in build_model._source_mark("roster-only")
    assert "no Top/Bot recorded" in build_model._source_mark("roster-only")


def test_tool_badge_shows_the_tier_and_enhancement():
    html_ = build_model._tool_badge(
        {"tool": False, "tool_item": "Rainbow Chisel", "tool_enhance": 4,
         "tool_source": "roster"}
    )
    assert "Rbw" in html_ and "+4" in html_
    assert "Rainbow Chisel" in html_


def test_tool_badge_falls_back_to_the_checkbox_when_the_roster_said_nothing():
    on = build_model._tool_badge(
        {"tool": True, "tool_item": None, "tool_source": "manual"})
    off = build_model._tool_badge(
        {"tool": False, "tool_item": None, "tool_source": "manual"})
    assert "badge on" in on and ">T<" in on
    assert "badge off" in off


def test_tool_badge_is_outlined_for_an_unmodelled_item():
    html_ = build_model._tool_badge(
        {"tool": True, "tool_item": None,
         "tool_source": "manual (unknown item: Obsidian Brush)"}
    )
    assert "badge unknown" in html_
    assert "Obsidian Brush" in html_


def test_caveats_state_the_assumption_while_the_roster_is_off():
    texts = build_model._caveat_texts(build_model._provenance_placeholder(107))
    assert "assumed to run a <code>+7</code> tool" in texts["tool_caveat"]
    assert "assumed default" in texts["house_caveat"]
    assert texts["sigma_enh_clause"] == "enhancement levels away from the assumed +7"


def test_caveats_stop_claiming_what_the_roster_has_made_false():
    """A stale caption is worse than none (src/draw.py's docstring)."""
    texts = build_model._caveat_texts(_prov_on())
    assert "observed, not assumed" in texts["tool_caveat"]
    assert "assumed to run a <code>+7</code> tool" not in texts["tool_caveat"]
    assert "no longer means a guessed" in texts["house_caveat"]
    assert "roster has not seen" in texts["sigma_enh_clause"]


def test_a_refused_roster_restores_the_assumption_caveats():
    texts = build_model._caveat_texts(_prov_on(refused="join rate too low"))
    assert "assumed to run a <code>+7</code> tool" in texts["tool_caveat"]


def test_roster_entries_carry_provenance_through_to_the_page():
    members = [_member("Yedic", level=110)]
    rows = roster.parse(_roster_csv([{"name": "Yedic"}]))
    merged, _prov = roster.merge(members, roster.join(members, rows), "sc")
    trials.audit_roster_tools(merged)
    result = trials.simulate_race(merged, "Milking")
    entry = result.roster[0]
    assert entry.source == "roster"
    assert entry.tool_item == "Celestial Brush"
    assert entry.tool_enhance == 10
    assert entry.tool_source == "roster"
    # And it survives the trip through to_dict, which is what the page reads.
    d = result.to_dict()["roster"][0]
    assert d["source"] == "roster" and d["tool_item"] == "Celestial Brush"


def test_roster_entry_defaults_to_manual_for_an_unmerged_member():
    entry = trials.simulate_race([_member("plain", level=110)], "Milking").roster[0]
    assert entry.source == "manual"
    assert entry.tool_item is None
    assert entry.tool_source == "manual"
