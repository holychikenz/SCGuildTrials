"""Unit tests for reader.parse. No network access.

The inline fixture replicates the real 3-header-row structure:
  row 1: notes
  row 2: group labels
  row 3: real header (with sentinel cells)
  rows 4+: member data, terminated by a blank Member cell.
"""

import pytest

from src.reader import SheetStructureError, parse

# Column layout (0-based), mirroring config.py:
#   0 Member | 1 Main Classes | 2 Flex | 3-7 flex levels
#   8+ skill blocks of [level, Tool, Top, Bot] x 10 skills
# We build rows with the correct offsets. Skill block 1 (Milking) at col 8.

_NOTE_ROW = "SURVEY CORPS,notes,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,"
_GROUP_ROW = (
    ",labels,,30+,25+,35+,35+,35+,Milking,,,,Foraging,,,,Woodcutting,,,,"
    "C.Smithing,,,,Crafting,,,,Tailoring,,,,Cooking,,,,Brewing,,,,"
    "Bell Farming,,,,Enhancing,,,"
)
_HEADER_ROW = (
    "Member,Main Classes ,Flex,,,,,,,Tool,Top,Bot,,Tool,Top,Bot,,Tool,Top,Bot,"
    ",Tool,Top,Bot,,Tool,Top,Bot,,Tool,Top,Bot,,Tool,Top,Bot,,Tool,Top,Bot,"
    ",Tool,Top,Bot,,Tool,Top,Bot"
)


def _member_row(name, main, flex, flex_levels, skill_specs):
    """Assemble a CSV data row.

    flex_levels: 5 strings for cols 3-7.
    skill_specs: list of 10 tuples (level, tool, top, bot) as strings.
    """
    cells = [name, main, flex] + list(flex_levels)
    for level, tool, top, bot in skill_specs:
        cells.extend([level, tool, top, bot])
    # Quote flex if it contains commas.
    out = []
    for c in cells:
        if "," in c:
            out.append(f'"{c}"')
        else:
            out.append(c)
    return ",".join(out)


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
