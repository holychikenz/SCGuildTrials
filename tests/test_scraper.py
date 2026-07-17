"""Unit tests for scraper.parse_gviz / GuildData. No network access.

The inline fixtures replicate the *gviz* CSV shape (which differs from the
export?format=csv shape covered by test_reader.py):
  - one merged, fully-quoted header row (row 1), with merged junk text
    prepended and trailing spaces on some cells;
  - member data from row 2 onward, terminated by a blank Member cell;
  - trailing "summary" junk columns after the real 59-column table.
"""

import json

import pytest

from src.reader import MemberRow, SheetStructureError
from src.scraper import GuildData, parse_gviz

# Skill-name header cells as gviz serves them: merged junk / trailing spaces.
# 0-based col of each 5-column block's level cell -> observed header text.
# (Post 2026-07-17 sheet change: leading column + per-skill "H" column, stride 5.)
_SKILL_HEADER_TEXT = {
    9: "Tool is for Celestial Milking ",
    14: "Foraging ",
    19: "Woodcutting ",
    24: "C.Smithing ",
    29: "Crafting ",
    34: "Tailoring ",
    39: "Cooking ",
    44: "Brewing ",
    49: "Bell Farming ",
    54: "Enhancing ",
}

# Rightmost real column (Enhancing Bot) + 1: the member table is 59 cols wide.
_N_COLS = 59


def _quote_row(cells):
    """Join cells as a fully-quoted CSV line, the way gviz emits them."""
    return ",".join('"' + str(c).replace('"', '""') + '"' for c in cells)


def _gviz_header(col1="SURVEY CORPS Member", col3="Flex"):
    """Build a 59-cell merged gviz header row mirroring the live sheet."""
    cells = [""] * _N_COLS
    cells[1] = col1  # Member (col 0 is the new leading column)
    cells[2] = "Flex is for your alternate weapons ... Main Classes "
    cells[3] = col3
    cells[4], cells[5], cells[6], cells[7], cells[8] = (
        "30+ ", "25+ ", "35+ ", "35+ ", "35+ ",
    )
    for base, text in _SKILL_HEADER_TEXT.items():
        cells[base] = text            # skill-name / level cell
        cells[base + 1] = "H"         # house-level column (new)
        cells[base + 2] = "Tool"
        cells[base + 3] = "Top"
        cells[base + 4] = "Bot"
    return cells


def _ten_skills(level="100"):
    return [(level, "FALSE", "FALSE", "FALSE") for _ in range(10)]


def _data_cells(name, main, flex, flex_levels, skill_specs,
                trailing_junk=None, lead="", houses=None):
    """Assemble a data row's cells (cols 0..58) plus optional trailing junk.

    lead: the new leading column (col 0).
    flex_levels: 5 strings for cols 4-8.
    skill_specs: 10 tuples (level, tool, top, bot) as strings.
    houses: 10 house-level strings (one per skill); defaults to all blank.
    """
    houses = houses if houses is not None else [""] * 10
    cells = [lead, name, main, flex] + list(flex_levels)  # cols 0..8
    for (level, tool, top, bot), house in zip(skill_specs, houses):
        cells.extend([level, house, tool, top, bot])  # cols 9..58 (stride 5)
    if trailing_junk:
        cells.extend(trailing_junk)  # cols 59+ (must be sliced away)
    return cells


def _csv(*data_rows, header=None):
    lines = [_quote_row(header if header is not None else _gviz_header())]
    lines += [_quote_row(c) for c in data_rows]
    return "\n".join(lines) + "\n"


def test_happy_path_parses_members():
    skills = _ten_skills("113")
    skills[0] = ("113", "TRUE", "FALSE", "FALSE")  # Milking: owns Tool
    skills[1] = ("119", "FALSE", "TRUE", "FALSE")  # Foraging: owns Top
    row = _data_cells("Feal", "Water", "Nature", ["", "", "", "", "47"], skills)

    members = parse_gviz(_csv(row))

    assert len(members) == 1
    m = members[0]
    assert m.name == "Feal"
    assert m.main_classes == "Water"
    assert m.flex == "Nature"
    assert m.flex_levels == [None, None, None, None, 47]
    assert m.skills["Milking"].level == 113
    assert m.skills["Milking"].tool is True
    assert m.skills["Milking"].top is False
    assert m.skills["Foraging"].top is True
    assert set(m.skills.keys()) == {
        "Milking", "Foraging", "Woodcutting", "C.Smithing", "Crafting",
        "Tailoring", "Cooking", "Brewing", "Bell Farming", "Enhancing",
    }


def test_boolean_and_none_coercion():
    skills = _ten_skills("")  # all levels blank -> None
    skills[0] = ("", "true", "FALSE", "TRUE")  # lowercase 'true' still True
    row = _data_cells("X", "", "", ["", "", "", "", ""], skills)

    m = parse_gviz(_csv(row))[0]
    assert m.skills["Milking"].level is None
    assert m.skills["Milking"].tool is True
    assert m.skills["Milking"].top is False
    assert m.skills["Milking"].bot is True
    assert m.flex_levels == [None] * 5
    assert m.main_classes == ""


def test_trailing_junk_columns_are_sliced_off():
    # Real gviz rows carry a side-summary after col 58; it must be ignored.
    junk = ["", "Average levels", "", "", "Milking", "117", "119", "TRUE"]
    row = _data_cells(
        "Feal", "Water", "Nature", ["", "", "", "", "47"],
        _ten_skills("113"), trailing_junk=junk,
    )

    members = parse_gviz(_csv(row))
    assert len(members) == 1
    m = members[0]
    assert m.name == "Feal"
    # Enhancing (last block, Bot at col 58) parses cleanly despite the junk.
    assert m.skills["Enhancing"].level == 113
    assert m.skills["Enhancing"].bot is False


def test_stops_at_blank_member_cell():
    r1 = _data_cells("Alpha", "A", "", ["", "", "", "", ""], _ten_skills())
    blank = [""] * _N_COLS
    r2 = _data_cells("Beta", "B", "", ["", "", "", "", ""], _ten_skills())
    # Beta appears AFTER a blank row and must be excluded.
    members = parse_gviz(_csv(r1, blank, r2))
    assert [m.name for m in members] == ["Alpha"]


def test_wrong_tab_guard_rejects_trial_assignments_shape():
    # gviz silently serves "Trial Assignments" for unknown names; its header
    # begins "    ","ALL TRIALS ARE FREE ASSIGNED...","Cut-Off(30)",...
    trial_header = [""] * _N_COLS
    trial_header[0] = "    "
    trial_header[1] = "ALL TRIALS ARE FREE ASSIGNED, PLEASE READ THE RULES"
    trial_header[2] = "Cut-Off(30)"
    bad_csv = _csv(["", "", ""], header=trial_header)

    with pytest.raises(SheetStructureError) as exc:
        parse_gviz(bad_csv)
    assert "did not match the expected member table" in str(exc.value)


def test_nonexistent_tab_behaves_as_wrong_tab():
    # A nonexistent tab yields the same Trial-Assignments payload from gviz,
    # so parse_gviz must reject it via the same header guard.
    trial_header = [""] * _N_COLS
    trial_header[0] = "    "
    trial_header[2] = "Cut-Off(30)"
    with pytest.raises(SheetStructureError):
        parse_gviz(_csv(["", "", ""], header=trial_header))


def test_empty_csv_raises_structure_error():
    with pytest.raises(SheetStructureError):
        parse_gviz("")


def test_guilddata_to_dict_is_json_serializable_and_shaped():
    row = _data_cells("Feal", "Water", "Nature", ["", "", "", "", "47"],
                      _ten_skills("113"))
    members = parse_gviz(_csv(row))
    gd = GuildData(
        tab="SC Member Data", fetched_at="2026-07-17T00:00:00+00:00",
        member_count=len(members), members=members,
    )

    d = gd.to_dict()
    # Round-trips through JSON without error.
    round_tripped = json.loads(json.dumps(d))
    assert round_tripped["tab"] == "SC Member Data"
    assert round_tripped["member_count"] == 1
    m = round_tripped["members"][0]
    # Member shape matches the existing data.json serialization (asdict).
    assert set(m.keys()) == {"name", "main_classes", "flex", "flex_levels", "skills"}
    assert m["skills"]["Milking"] == {
        "level": 113, "tool": False, "top": False, "bot": False, "house": None,
    }
    assert isinstance(members[0], MemberRow)
