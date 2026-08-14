"""Unit tests for the weekly trial-draw reader. No network access.

REWRITTEN 2026-08-14, and the reason matters more than the tests do.

This file used to hold ~24 tests across TWO transcribed shapes of the
hand-maintained "Trial Assignments" tab — a ``Skilling Trial Info`` banner with
``Trial N`` rows, and a right-hand ``Trial Priority`` table. Every one of them
passed on the day the officers rebuilt that tab a third time and deleted both
anchors. The tests were green; the site published the wrong four trials for a day.

That is the shape of the failure worth remembering: a fixture transcribed from a
hand-maintained sheet tests only that we still parse what somebody once typed, and
says nothing about whether they will keep typing it. So the draw now comes from the
one tab the GAME writes (``config.DRAW_SOURCE_TAB``) and the fixtures below are its
header row — a row whose shape is the game's contract with its own sign-up
tick-boxes, not an officer's layout preference.

The two live fixtures are transcribed verbatim from 2026-08-14, and the pair is the
point: Survey Corps' tab had been refreshed to the 8/14 cycle and Lactose
lntolerance's had not, which is exactly the condition ``build._fetch_guild`` now has
to notice.
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


def _header(*cells: str) -> str:
    """A sign-up tab reduced to the one row the draw is read from.

    Only the header row matters here; the tick-box rows below it are
    ``signup.parse_signup``'s business and are tested there. A single member row is
    included so the fixture is a plausible tab rather than a lone line.
    """
    return _csv([list(cells), ["Somebody", *["FALSE"] * (len(cells) - 1)]])


# The REAL header rows, 2026-08-14. SC is the draw source; LI is a tab the game had
# not yet refreshed, and still carried the whole of the 8/10 cycle — its four skills
# AND both its combat bosses, which is what rules out "LI genuinely drew differently".
_SC_LIVE = ("User", "Enhancing", "Milking", "Cooking", "Brewing", "Hedgehog", "Swarm")
_LI_LIVE_STALE = (
    "User", "Cooking", "Woodcutting", "C.Smithing", "Crafting", "Chameleon", "Swarm",
)

# What each of those tabs says the four skilling trials are, in internal trial-skill
# names and in the game's own column order.
_SC_DRAW = ["Enhancing", "Milking", "Cooking", "Brewing"]
_LI_STALE_DRAW = ["Cooking", "Woodcutting", "C.Smithing", "Crafting"]


# ---------------------------------------------------------------------------
# The happy path, against the live row
# ---------------------------------------------------------------------------
def test_reads_the_four_skilling_columns_from_the_live_header():
    assert draw.parse_draw(_header(*_SC_LIVE)).skills == _SC_DRAW


def test_column_order_is_the_games_order_not_a_priority():
    # The retired Trial Priority table ranked the four trials 1-4; this source has
    # no ranking at all, so the order is columns B-E left to right and means nothing
    # more. Pinned because signup.plan reads this order for lock precedence, so a
    # silent re-ordering would silently change which lock wins.
    draw_result = draw.parse_draw(_header(*_SC_LIVE))
    assert draw_result.skills[0] == "Enhancing"   # column B
    assert draw_result.skills[-1] == "Brewing"    # column E


def test_combat_columns_are_ignored_by_position():
    # Hedgehog and Swarm sit in F and G. They are not skills and would raise if the
    # block were read one column too wide, which is what makes this a real assertion
    # rather than a restatement of the fixture.
    assert "Hedgehog" not in draw.parse_draw(_header(*_SC_LIVE)).skills
    assert "Swarm" not in draw.parse_draw(_header(*_SC_LIVE)).skills


def test_extra_trailing_columns_are_tolerated():
    # The game has added trailing helper columns before now; only B-E are read.
    header = (*_SC_LIVE, "", "Notes", "anything at all")
    assert draw.parse_draw(_header(*header)).skills == _SC_DRAW


# ---------------------------------------------------------------------------
# Label normalisation
# ---------------------------------------------------------------------------
def test_cheesesmithing_is_aliased_to_the_internal_name():
    header = ("User", "Cheesesmithing", "Milking", "Cooking", "Brewing")
    assert draw.parse_draw(_header(*header)).skills[0] == "C.Smithing"


def test_the_internal_c_smithing_spelling_also_reads():
    # LI's live tab used this spelling where SC's used the long one, so both must go.
    assert draw.trial_columns(_header(*_LI_LIVE_STALE), "LI") == _LI_STALE_DRAW


def test_bell_farming_is_accepted_as_alchemy():
    # Defensive: the game heads the SIGN-UP column "Alchemy", but the member tab
    # calls that same skill "Bell Farming". If the game ever switches to the sheet's
    # own label the draw should keep reading rather than fail on a name we know.
    header = ("User", "Bell Farming", "Milking", "Cooking", "Brewing")
    assert draw.parse_draw(_header(*header)).skills[0] == "Alchemy"


def test_skill_labels_are_case_insensitive():
    header = ("User", "eNhAnCiNg", "milking", "COOKING", "Brewing")
    assert draw.parse_draw(_header(*header)).skills == _SC_DRAW


def test_surrounding_whitespace_is_tolerated():
    header = ("User ", " Enhancing", "Milking ", " Cooking ", "Brewing")
    assert draw.parse_draw(_header(*header)).skills == _SC_DRAW


# ---------------------------------------------------------------------------
# Loud failure. Every one of these used to be a silently-wrong draw.
# ---------------------------------------------------------------------------
def test_missing_user_sentinel_raises():
    # gviz does NOT error on an unknown tab name — it serves a DIFFERENT tab. This
    # sentinel is the only thing between a typo in DRAW_SOURCE_TAB and a confidently
    # parsed draw belonging to some other table entirely.
    header = ("Member", "Enhancing", "Milking", "Cooking", "Brewing")
    with pytest.raises(SheetStructureError) as exc:
        draw.parse_draw(_header(*header))
    assert "User" in str(exc.value)


def test_too_few_columns_raises():
    header = ("User", "Enhancing", "Milking")  # only two trials
    with pytest.raises(SheetStructureError) as exc:
        draw.parse_draw(_header(*header))
    assert "too few columns" in str(exc.value)


def test_unrecognised_skilling_header_raises():
    # A combat boss that has drifted left into the skilling block, a renamed skill,
    # or a typo. Never guessed past: the draw is the input to everything.
    header = ("User", "Enhancing", "Chameleon", "Cooking", "Brewing")
    with pytest.raises(SheetStructureError) as exc:
        draw.parse_draw(_header(*header))
    assert "Chameleon" in str(exc.value)


def test_the_error_names_the_offending_spreadsheet_column():
    # So a reader of the CI log can open the sheet at the right cell.
    header = ("User", "Enhancing", "Milking", "Cooking", "Nonsense")
    with pytest.raises(SheetStructureError) as exc:
        draw.parse_draw(_header(*header))
    assert "column 4" in str(exc.value) and "E" in str(exc.value)


def test_a_blank_skilling_header_raises():
    # An emptied cell is a layout change, not "no trial this week".
    header = ("User", "Enhancing", "", "Cooking", "Brewing")
    with pytest.raises(SheetStructureError):
        draw.parse_draw(_header(*header))


def test_empty_csv_raises():
    with pytest.raises(SheetStructureError) as exc:
        draw.parse_draw("")
    assert "empty" in str(exc.value)


def test_there_is_no_layout_fallback():
    # The retired anchors must NOT be honoured. A tab that still carries an old-style
    # "Trial Priority" table but no sign-up header row is a wrong tab, and saying so
    # is the whole lesson of 2026-08-14: a chain of fallbacks across hand-made shapes
    # is what let a stale draw ship quietly.
    legacy = _csv([
        ["", "Trial Priority", ""],
        ["", "Milking", "3"],
        ["", "Cooking", "1"],
    ])
    with pytest.raises(SheetStructureError):
        draw.parse_draw(legacy)


# ---------------------------------------------------------------------------
# What this source does NOT carry, stated so a regression reads as a change
# ---------------------------------------------------------------------------
def test_there_is_no_cycle_date():
    # The retired banner published one; this tab does not. Carried as "" rather than
    # removed so the page and callers need not change (it was logging only).
    assert draw.parse_draw(_header(*_SC_LIVE)).date == ""


def test_there_are_no_minimum_sign_up_levels():
    # The per-trial minimum sign-up level (2026-08-11) lived in a third column of the
    # Trial Priority table. The officers deleted that table, so the datum exists
    # nowhere on the sheet and every trial is unrestricted — which is precisely the
    # documented rollback state of that feature, not a parsing failure.
    assert draw.parse_draw(_header(*_SC_LIVE)).min_levels == {}


# ---------------------------------------------------------------------------
# The staleness cross-check primitive (build._fetch_guild's input)
# ---------------------------------------------------------------------------
def test_trial_columns_reads_any_guilds_tab():
    # Same primitive, pointed at a guild's own tab rather than the draw source. This
    # is how build.py compares a guild's ticks against the week actually drawn.
    assert draw.trial_columns(_header(*_SC_LIVE), "SC Trial Signup") == _SC_DRAW
    assert (
        draw.trial_columns(_header(*_LI_LIVE_STALE), "LI Trial Signup")
        == _LI_STALE_DRAW
    )


def test_the_live_2026_08_14_tabs_disagree():
    # The regression fixture for the bug itself. Both rows are valid, both parse, and
    # every label in both is a real skill — which is exactly why nothing noticed that
    # one of them was a week out of date. Compared as SETS, because the game orders
    # these columns as it pleases and a re-ordering is not a stale week.
    sc = set(draw.trial_columns(_header(*_SC_LIVE), "SC"))
    li = set(draw.trial_columns(_header(*_LI_LIVE_STALE), "LI"))
    assert sc != li


def test_a_reordered_tab_is_not_treated_as_stale():
    # The other half of that rule: same four trials, different columns, same week.
    shuffled = ("User", "Brewing", "Cooking", "Enhancing", "Milking", "Hedgehog")
    assert set(draw.trial_columns(_header(*shuffled), "SC")) == set(_SC_DRAW)


# ---------------------------------------------------------------------------
# The fetch
# ---------------------------------------------------------------------------
def test_fetch_does_not_disable_gviz_header_collapsing(monkeypatch):
    """The INVERSE of the assertion this file used to carry, and deliberately so.

    ``&headers=0`` (``config.GVIZ_NO_HEADER_COLLAPSE``) existed because the old tab's
    banner sat beneath whatever prose the officers wrote above it, and gviz's header
    guess would swallow the draw rows. Here the header row IS the draw, and that
    override would hide the one line we want. Pinned so a well-meaning "restore the
    override" cannot quietly blind the parser.
    """
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
    draw.fetch_draw_csv()
    assert config.GVIZ_NO_HEADER_COLLAPSE not in seen["url"]
    assert "SC%20Trial%20Signup" in seen["url"]


def test_fetch_addresses_the_configured_draw_tab():
    # One knob, one source. If this drifts from config, the cross-check in build.py
    # would be comparing a guild's tab against some other tab's week.
    assert draw.DRAW_TAB == config.DRAW_SOURCE_TAB == "SC Trial Signup"


def test_the_skilling_block_geometry_matches_the_signup_parser():
    # draw.py reads the four HEADERS; signup.parse_signup reads the ticks beneath the
    # same four columns. They are separate constants in separate modules, so pin that
    # they agree — a drift would have one module reading a column the other ignores.
    from src import signup

    assert draw.SKILLING_COL_START == signup.SKILLING_COL_START
    assert draw.EXPECTED_TRIALS == signup.SKILLING_COL_COUNT
