"""Unit tests for reader.parse. No network access.

The inline fixture replicates the real 3-header-row structure:
  row 1: notes
  row 2: group labels
  row 3: real header (with sentinel cells)
  rows 4+: member data, terminated by a blank Member cell.
"""

import pytest

from src.reader import SheetStructureError, parse

# Column layout (0-based), mirroring config.py (post 2026-07-17 sheet change):
#   0 lead | 1 Member | 2 Main Classes | 3 Flex | 4-8 flex levels
#   9+ skill blocks of [level, H (house), Tool, Top, Bot] x 10 skills (stride 5)
# We build rows with the correct offsets. Skill block 1 (Milking) at col 9.


def _row(cells):
    """Join cells into a CSV line, quoting any cell containing a comma."""
    return ",".join(f'"{c}"' if "," in c else c for c in cells)


_NOTE_ROW = _row([""] * 59)   # row 0: notes (ignored by the parser)
_GROUP_ROW = _row([""] * 59)  # row 1: group labels (ignored by the parser)


def _header_cells():
    """Row 2 (the validated header): lead, Member, Main Classes, Flex, then a
    5-cell block per skill: [<level blank>, H, Tool, Top, Bot]."""
    cells = ["", "Member", "Main Classes ", "Flex", "", "", "", "", ""]
    for _ in range(10):
        cells.extend(["", "H", "Tool", "Top", "Bot"])
    return cells


_HEADER_ROW = _row(_header_cells())


def _member_row(name, main, flex, flex_levels, skill_specs, lead="", houses=None):
    """Assemble a CSV data row.

    flex_levels: 5 strings for cols 4-8.
    skill_specs: list of 10 tuples (level, tool, top, bot) as strings.
    lead: the new leading column (col 0).
    houses: 10 house-level strings (one per skill); defaults to all blank.
    """
    houses = houses if houses is not None else [""] * 10
    cells = [lead, name, main, flex] + list(flex_levels)  # cols 0..8
    for (level, tool, top, bot), house in zip(skill_specs, houses):
        cells.extend([level, house, tool, top, bot])  # [level, H, Tool, Top, Bot]
    return _row(cells)


def _ten_skills(level="100"):
    return [(level, "FALSE", "FALSE", "FALSE") for _ in range(10)]


def _csv(*data_rows):
    return "\n".join([_NOTE_ROW, _GROUP_ROW, _HEADER_ROW, *data_rows]) + "\n"


def test_happy_path_parses_members():
    skills = _ten_skills("113")
    skills[0] = ("113", "TRUE", "FALSE", "FALSE")  # Milking: owns Tool
    skills[1] = ("119", "FALSE", "TRUE", "FALSE")  # Foraging: owns Top
    row = _member_row("Feal", "Water", "Nature", ["", "", "", "", "47"], skills)
    members = parse(_csv(row))

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


def test_house_level_parsed_from_h_column():
    skills = _ten_skills("113")
    # Milking house 4, Woodcutting house 6, the rest blank.
    houses = ["4", "", "6", "", "", "", "", "", "", ""]
    row = _member_row(
        "Feal", "Water", "Nature", ["", "", "", "", "47"], skills, houses=houses
    )
    m = parse(_csv(row))[0]
    assert m.skills["Milking"].house == 4
    assert m.skills["Foraging"].house is None
    assert m.skills["Woodcutting"].house == 6


def test_boolean_and_none_coercion():
    skills = _ten_skills("")  # all levels blank -> None
    skills[0] = ("", "true", "FALSE", "TRUE")  # lowercase true still True
    row = _member_row("X", "", "", ["", "", "", "", ""], skills)
    m = parse(_csv(row))[0]

    assert m.skills["Milking"].level is None
    assert m.skills["Milking"].tool is True      # 'true' (case-insensitive)
    assert m.skills["Milking"].top is False
    assert m.skills["Milking"].bot is True
    assert m.flex_levels == [None] * 5
    assert m.main_classes == ""


def test_stops_at_blank_member_cell():
    r1 = _member_row("Alpha", "A", "", ["", "", "", "", ""], _ten_skills())
    blank = ",,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,"
    r2 = _member_row("Beta", "B", "", ["", "", "", "", ""], _ten_skills())
    # Beta appears AFTER a blank row and must be excluded.
    members = parse(_csv(r1, blank, r2))
    assert [m.name for m in members] == ["Alpha"]


def test_quoted_flex_with_commas():
    row = _member_row(
        "Nidras", "Smash/Stab", "Cursed, Regal, Bulwark",
        ["34", "27", "38", "37", "38"], _ten_skills("120"),
    )
    m = parse(_csv(row))[0]
    assert m.flex == "Cursed, Regal, Bulwark"
    assert m.flex_levels == [34, 27, 38, 37, 38]


def test_structure_guard_raises_on_bad_header():
    bad_header = "Nope,Wrong,Header,,,,,,,X,Y,Z"
    bad_csv = "\n".join([_NOTE_ROW, _GROUP_ROW, bad_header, "a,b,c"]) + "\n"
    with pytest.raises(SheetStructureError) as exc:
        parse(bad_csv)
    assert "structure has changed" in str(exc.value)


def test_structure_guard_raises_on_too_few_rows():
    with pytest.raises(SheetStructureError):
        parse("only,one,row\n")
