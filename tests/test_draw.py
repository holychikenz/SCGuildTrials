"""Unit tests for the weekly trial-draw reader. No network access.

The fixtures mirror the REAL "Trial Assignments" tab as served by gviz with
header-collapsing disabled (``config.GVIZ_NO_HEADER_COLLAPSE``) — including the
16-row free-assignment notice the officers put above the draw on 2026-07-25,
which is what broke the deploy: gviz's header guess grew to swallow the banner
and all four draw rows, so the parser saw neither.
"""

import csv
import io

import pytest

from src import config, draw
from src.reader import SheetStructureError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _csv(rows: list[list[str]]) -> str:
    """Render a row matrix as CSV text, exactly as gviz would serve it."""
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


def _row(**cells) -> list[str]:
    """Build a 13-column row from ``c<index>=value`` keyword pairs."""
    row = [""] * 13
    for key, value in cells.items():
        row[int(key[1:])] = value
    return row


# The live layout (2026-07-25): notice block, the ten free-assignment skill
# labels, a pointer to the generated site, THEN the skilling draw, then combat.
_NOTICE_BLOCK = [
    _row(c1='ALL TRIALS ARE "FREE" ASSIGNED'),
    _row(c1='You are "free" to decide which Trial you want to join'),
    _row(c1="Skilling Trials"),
    _row(c1="Survey Corps", c4="Lactose Intolerant"),
    _row(c2="Cut-Off(30)", c5="Cut-Off(30)", c11="IMPORTANT"),
    *[
        _row(c1=skill, c4=skill)
        for skill in (
            "Milking", "Foraging", "Woodcutting", "Cheesesmithing", "Crafting",
            "Tailoring", "Cooking", "Brewing", "Alchemy", "Enhancing",
        )
    ],
    _row(c1="REFER TO THE NEW TRIAL ASSIGNMENTS SHEET"),
    _row(c1="https://holychikenz.github.io/SC"),
]

_COMBAT_BLOCK = [
    _row(c1="Combat Trials"),
    _row(c1="These are the fixed members"),
    _row(c1="Combat Trail Info", c2="Date:  7/24", c4="Priority"),
    _row(c1="Trial 1", c2="Jellyfish", c4="Range/Nature"),
    _row(c1="Trial 2", c2="Hedgehog", c4="Neutral"),
]


def _live_layout(
    skills=("Milking", "Woodcutting", "Crafting", "Alchemy"), date="Date: 7/24"
) -> str:
    rows = [
        *_NOTICE_BLOCK,
        _row(c1="Skilling Trial Info", c2=date, c4="Priority"),
        *[
            _row(c1=f"Trial {i}", c2=skill)
            for i, skill in enumerate(skills, start=1)
        ],
        *_COMBAT_BLOCK,
    ]
    return _csv(rows)


# ---------------------------------------------------------------------------
# The 2026-07-25 regression: a notice block above the draw
# ---------------------------------------------------------------------------
def test_draw_parses_below_the_free_assignment_notice():
    # THE REGRESSION TEST. 16 rows of notice sit above the banner; the parser
    # must still find the draw beneath them.
    d = draw.parse_draw(_live_layout())
    assert d.skills == ["Milking", "Woodcutting", "Crafting", "Alchemy"]
    assert d.date == "7/24"


def test_draw_ignores_the_ten_free_assignment_skill_labels():
    # The notice block lists all ten skills in column 1 — none of them may leak
    # into the draw, which is anchored on the banner and the "Trial N" rows.
    d = draw.parse_draw(_live_layout())
    assert len(d.skills) == draw.EXPECTED_TRIALS == 4
    assert "Foraging" not in d.skills   # listed in the notice, not drawn
    assert "Enhancing" not in d.skills


def test_combat_section_never_bleeds_into_the_skilling_draw():
    # The combat block below carries its own "Trial 1"/"Trial 2" rows under a
    # distinct banner; the skilling draw must stop before them.
    d = draw.parse_draw(_live_layout())
    assert "Jellyfish" not in d.skills and "Hedgehog" not in d.skills


# ---------------------------------------------------------------------------
# Parsing details
# ---------------------------------------------------------------------------
def test_cheesesmithing_is_aliased_to_the_internal_name():
    d = draw.parse_draw(
        _live_layout(skills=("Cheesesmithing", "Milking", "Cooking", "Brewing"))
    )
    assert d.skills[0] == "C.Smithing"
    assert all(s in config.TRIAL_SKILL_TO_SHEET_COLUMN for s in d.skills)


def test_skill_labels_are_case_insensitive():
    d = draw.parse_draw(
        _live_layout(skills=("milking", "WOODCUTTING", "Crafting", "alchemy"))
    )
    assert d.skills == ["Milking", "Woodcutting", "Crafting", "Alchemy"]


def test_date_tolerates_a_missing_prefix():
    d = draw.parse_draw(_live_layout(date="7/31"))
    assert d.date == "7/31"


def test_blank_spacer_between_banner_and_first_trial_is_tolerated():
    rows = [
        *_NOTICE_BLOCK,
        _row(c1="Skilling Trial Info", c2="Date: 7/24"),
        _row(),  # spacer
        *[
            _row(c1=f"Trial {i}", c2=s)
            for i, s in enumerate(
                ("Milking", "Woodcutting", "Crafting", "Alchemy"), start=1
            )
        ],
    ]
    assert draw.parse_draw(_csv(rows)).skills[0] == "Milking"


# ---------------------------------------------------------------------------
# Loud failures (the parser must never guess a draw)
# ---------------------------------------------------------------------------
def test_missing_banner_raises():
    rows = [*_NOTICE_BLOCK, *_COMBAT_BLOCK]  # no skilling banner at all
    with pytest.raises(SheetStructureError, match="Skilling Trial Info"):
        draw.parse_draw(_csv(rows))


def test_wrong_trial_count_raises():
    with pytest.raises(SheetStructureError, match="Expected 4"):
        draw.parse_draw(_live_layout(skills=("Milking", "Crafting")))


def test_unrecognised_skill_raises():
    with pytest.raises(SheetStructureError, match="Unrecognised"):
        draw.parse_draw(
            _live_layout(skills=("Milking", "Woodcutting", "Crafting", "Fishing"))
        )


def test_empty_csv_raises():
    with pytest.raises(SheetStructureError):
        draw.parse_draw("")


# ---------------------------------------------------------------------------
# The fetch must disable gviz's header guessing
# ---------------------------------------------------------------------------
def test_fetch_disables_gviz_header_collapsing(monkeypatch):
    # Without &headers=0 gviz decides for itself how many leading rows are
    # labels, and a notice added above the table hides the draw. This assertion
    # is the guard against that regression returning.
    seen = {}

    class _Resp:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

    def fake_get(url, timeout=None):
        seen["url"] = url
        return _Resp()

    monkeypatch.setattr(draw.requests, "get", fake_get)
    draw.fetch_assignments_csv()
    assert config.GVIZ_NO_HEADER_COLLAPSE == "&headers=0"
    assert seen["url"].endswith("&headers=0")
    assert "Trial%20Assignments" in seen["url"]
