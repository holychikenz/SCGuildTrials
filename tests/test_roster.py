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
