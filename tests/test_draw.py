"""Unit tests for the weekly trial-draw reader. No network access.

The fixtures mirror the REAL "Trial Assignments" tab as served by gviz with
header-collapsing disabled (``config.GVIZ_NO_HEADER_COLLAPSE``), in BOTH shapes
the officers have published:

* ``_live_layout`` — the CURRENT tab (rebuilt 2026-07-31): a "Trial Priority"
  table off to the right, no "Trial N" slot labels, and no date on the skilling
  section (only the combat banner carries one). Transcribed from the live tab.
* ``_legacy_layout`` — the tab up to 2026-07-25: a "Skilling Trial Info" banner
  with one "Trial N" row per drawn skill, below the 16-row free-assignment
  notice whose growth once broke the deploy (gviz's header guess swallowed the
  banner and all four draw rows, so the parser saw neither).
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


# The ten trial-eligible skills, as listed down the per-guild cut-off tables.
# Both layouts print all ten in a left-hand column; none of them may leak into
# the draw, which is only ever the four the officers actually drew.
_TEN_SKILLS = (
    "Milking", "Foraging", "Woodcutting", "Cheesesmithing", "Crafting",
    "Tailoring", "Cooking", "Brewing", "Alchemy", "Enhancing",
)

# The draw live on the tab at the time of the 2026-07-31 rebuild.
_CURRENT_DRAW = ("Milking", "Foraging", "Crafting", "Alchemy")


# ---------------------------------------------------------------------------
# Fixture: the CURRENT layout (tab rebuilt 2026-07-31)
# ---------------------------------------------------------------------------
# Combat is the only block left carrying a date, and its priority column is
# headed a bare "Priority" — which must NOT be mistaken for "Trial Priority".
_CURRENT_COMBAT_BLOCK = [
    _row(c1="Combat Trials"),
    _row(c1="Date: 7/31", c5="Survey Corps", c7="Lactose Intolerance",
         c10="Priority"),
    _row(c1="Trial 1", c3="Badger", c5="Team 1", c7="Team 1", c10="Mages"),
    _row(c1="Trial 2", c3="Hedgehog", c5="Team 2", c7="Team 2", c10="Neutral"),
]


def _live_layout(skills=_CURRENT_DRAW, priorities=("3", "4", "2", "1")) -> str:
    """The CURRENT tab: a right-hand "Trial Priority" table, no "Trial N" rows.

    The priority table (cols 10-11) overlaps the two per-guild cut-off tables
    (cols 1-2 and 5-6) row-wise, and is followed by a blank cell and then three
    lines of sign-up prose — the blank is what ends the block.
    """
    rows = [
        _row(c0="   ", c1="Skilling Trials"),
        _row(c1="Survey Corps", c10="Lactose Intolerance"),
        # 22 unlabelled tick-box rows, one per party seat (SC then LI). Since
        # the rebuild these columns carry no skill headers at all.
        *[
            _row(c2="FALSE", c4="FALSE", c6="FALSE", c8="FALSE",
                 c11="FALSE", c12="FALSE")
            for _ in range(22)
        ],
        _row(),
        _row(c1="Survey Corps", c4="Lactose Intolerant"),
        _row(c2="Cut-Off(30)", c6="Cut-Off(30)"),
        *[_row(c1=s, c2="120", c5=s, c6="113") for s in _TEN_SKILLS],
        _row(),
        *_CURRENT_COMBAT_BLOCK,
    ]

    # Paint the "Trial Priority" table into cols 10-11, alongside the cut-offs.
    banner = next(
        i for i, r in enumerate(rows)
        if r[1] == "Survey Corps" and r[4] == "Lactose Intolerant"
    )
    rows[banner][10] = draw.PRIORITY_SECTION
    for i, skill in enumerate(skills):
        rows[banner + 1 + i][10] = skill
        rows[banner + 1 + i][11] = priorities[i] if i < len(priorities) else ""

    # ...then a blank spacer, then the sign-up prose the block must stop before.
    prose = banner + 1 + len(skills) + 1
    for j, line in enumerate((
        "If you do not meet the cut-off, wait for the trial to fill up",
        "Players with Skilling Gear can join even below the cut-off",
        "Join the trial based on the priority order above",
    )):
        rows[prose + j][10] = line

    return _csv(rows)


# ---------------------------------------------------------------------------
# Fixture: the LEGACY layout (tab up to 2026-07-25)
# ---------------------------------------------------------------------------
# Notice block, the ten free-assignment skill labels, a pointer to the generated
# site, THEN the skilling draw, then combat.
_NOTICE_BLOCK = [
    _row(c1='ALL TRIALS ARE "FREE" ASSIGNED'),
    _row(c1='You are "free" to decide which Trial you want to join'),
    _row(c1="Skilling Trials"),
    _row(c1="Survey Corps", c4="Lactose Intolerant"),
    _row(c2="Cut-Off(30)", c5="Cut-Off(30)", c11="IMPORTANT"),
    *[_row(c1=skill, c4=skill) for skill in _TEN_SKILLS],
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


def _legacy_layout(
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
# The 2026-07-31 regression: the tab rebuilt around a "Trial Priority" table
# ---------------------------------------------------------------------------
def test_current_layout_parses_the_priority_table():
    # THE REGRESSION TEST. The officers rebuilt the tab: the "Skilling Trial
    # Info" banner and its four "Trial N" rows are gone, replaced by a
    # right-hand "Trial Priority" table. The parser must read the draw from it
    # rather than degrade to the last-known (and by then wrong) draw.
    d = draw.parse_draw(_live_layout())
    assert d.skills == ["Milking", "Foraging", "Crafting", "Alchemy"]


def test_current_layout_takes_the_cycle_date_from_the_combat_banner():
    # The rebuilt skilling section carries no date of its own; the tab's single
    # "Date: 7/31" now sits on the combat banner below it.
    assert draw.parse_draw(_live_layout()).date == "7/31"


def test_priority_table_ignores_the_ten_cut_off_skill_labels():
    # The two cut-off tables list all ten skills in cols 1 and 5, overlapping
    # the priority table row-wise. Only the banner's own column is read.
    d = draw.parse_draw(_live_layout())
    assert len(d.skills) == draw.EXPECTED_TRIALS == 4
    assert "Woodcutting" not in d.skills   # in the cut-off list, not drawn
    assert "Enhancing" not in d.skills


def test_priority_table_stops_at_the_blank_before_the_sign_up_prose():
    # Three lines of prose follow the four skills in the same column, separated
    # by one blank cell. Reading past the blank would raise "Unrecognised".
    assert draw.parse_draw(_live_layout()).skills[-1] == "Alchemy"


def test_bare_combat_priority_header_is_not_the_trial_priority_table():
    # The combat block heads its own column a plain "Priority". Anchoring on
    # that would read "Mages"/"Neutral" as skilling trials, so the sentinel is
    # the two-word "Trial Priority" — with neither anchor present, we fail loud.
    rows = [_row(c1="Skilling Trials"), *_CURRENT_COMBAT_BLOCK]
    with pytest.raises(SheetStructureError, match="Trial Priority"):
        draw.parse_draw(_csv(rows))


def test_current_layout_wrong_trial_count_raises():
    with pytest.raises(SheetStructureError, match="Expected 4"):
        draw.parse_draw(_live_layout(skills=("Milking", "Crafting")))


def test_current_layout_unrecognised_skill_raises():
    with pytest.raises(SheetStructureError, match="Unrecognised"):
        draw.parse_draw(
            _live_layout(skills=("Milking", "Foraging", "Crafting", "Fishing"))
        )


# ---------------------------------------------------------------------------
# The 2026-07-25 regression: a notice block above the LEGACY draw
# ---------------------------------------------------------------------------
def test_draw_parses_below_the_free_assignment_notice():
    # 16 rows of notice sit above the banner; the parser must still find the
    # draw beneath them.
    d = draw.parse_draw(_legacy_layout())
    assert d.skills == ["Milking", "Woodcutting", "Crafting", "Alchemy"]
    assert d.date == "7/24"


def test_draw_ignores_the_ten_free_assignment_skill_labels():
    # The notice block lists all ten skills in column 1 — none of them may leak
    # into the draw, which is anchored on the banner and the "Trial N" rows.
    d = draw.parse_draw(_legacy_layout())
    assert len(d.skills) == draw.EXPECTED_TRIALS == 4
    assert "Foraging" not in d.skills   # listed in the notice, not drawn
    assert "Enhancing" not in d.skills


def test_combat_section_never_bleeds_into_the_skilling_draw():
    # The combat block below carries its own "Trial 1"/"Trial 2" rows under a
    # distinct banner; the skilling draw must stop before them.
    d = draw.parse_draw(_legacy_layout())
    assert "Jellyfish" not in d.skills and "Hedgehog" not in d.skills


# ---------------------------------------------------------------------------
# Choosing between the two layouts
# ---------------------------------------------------------------------------
def test_legacy_block_wins_when_both_anchors_are_present():
    # If the officers ever restore the "Trial N" rows alongside the priority
    # table, the legacy block is preferred: it alone carries slot labels.
    rows = list(csv.reader(io.StringIO(_live_layout())))
    rows.append(_row(c1="Skilling Trial Info", c2="Date: 7/24", c4="Priority"))
    rows.extend(
        _row(c1=f"Trial {i}", c2=s)
        for i, s in enumerate(("Cooking", "Brewing", "Tailoring", "Milking"), 1)
    )
    assert draw.parse_draw(_csv(rows)).skills == [
        "Cooking", "Brewing", "Tailoring", "Milking",
    ]


def test_an_emptied_legacy_banner_does_not_shadow_the_priority_table():
    # A leftover banner with no "Trial N" rows under it carries no draw, so it
    # must fall through to the priority table rather than fail the build.
    rows = list(csv.reader(io.StringIO(_live_layout())))
    rows.append(_row(c1="Skilling Trial Info", c2="Date: 7/24", c4="Priority"))
    assert draw.parse_draw(_csv(rows)).skills == list(_CURRENT_DRAW)


# ---------------------------------------------------------------------------
# Parsing details (LEGACY layout)
# ---------------------------------------------------------------------------
def test_cheesesmithing_is_aliased_to_the_internal_name():
    d = draw.parse_draw(
        _legacy_layout(skills=("Cheesesmithing", "Milking", "Cooking", "Brewing"))
    )
    assert d.skills[0] == "C.Smithing"
    assert all(s in config.TRIAL_SKILL_TO_SHEET_COLUMN for s in d.skills)


def test_cheesesmithing_is_aliased_in_the_priority_table_too():
    d = draw.parse_draw(
        _live_layout(skills=("Cheesesmithing", "Milking", "Cooking", "Brewing"))
    )
    assert d.skills[0] == "C.Smithing"


def test_skill_labels_are_case_insensitive():
    d = draw.parse_draw(
        _legacy_layout(skills=("milking", "WOODCUTTING", "Crafting", "alchemy"))
    )
    assert d.skills == ["Milking", "Woodcutting", "Crafting", "Alchemy"]


def test_date_tolerates_a_missing_prefix():
    d = draw.parse_draw(_legacy_layout(date="7/31"))
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
def test_missing_both_banners_raises_naming_both():
    rows = [*_NOTICE_BLOCK, *_COMBAT_BLOCK]  # no skilling anchor at all
    with pytest.raises(SheetStructureError) as exc:
        draw.parse_draw(_csv(rows))
    assert "Skilling Trial Info" in str(exc.value)
    assert "Trial Priority" in str(exc.value)


def test_wrong_trial_count_raises():
    with pytest.raises(SheetStructureError, match="Expected 4"):
        draw.parse_draw(_legacy_layout(skills=("Milking", "Crafting")))


def test_unrecognised_skill_raises():
    with pytest.raises(SheetStructureError, match="Unrecognised"):
        draw.parse_draw(
            _legacy_layout(skills=("Milking", "Woodcutting", "Crafting", "Fishing"))
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
