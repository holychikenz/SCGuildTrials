"""Read this week's skilling-trial draw from the guild sheet.

The four skilling trials the guild runs each cycle are NOT a code constant — they
are drawn (seemingly randomly) each cycle. This module reads them from the
**sign-up tab the game itself writes** (``config.DRAW_SOURCE_TAB``, i.e.
"SC Trial Signup"), whose header row heads one tick-box column per drawn trial::

    User,Enhancing,Milking,Cooking,Brewing,Hedgehog,Swarm

Columns B–E (0-based 1..4) are the four SKILLING trials, in the game's own order.
Everything from column F on is the two COMBAT trials and is ignored by position —
the same fixed geometry :func:`src.signup.parse_signup` reads the tick-boxes
against, and for the same reason: the game writes this row, so its shape is the
game's, not an officer's.

WHY THIS TAB AND NOTHING ELSE (2026-08-14). The draw used to be read from the
hand-maintained "Trial Assignments" tab, in either of two shapes — a
``Skilling Trial Info`` banner with ``Trial N`` rows, or a two-column
``Trial Priority`` table. On 2026-08-14 the officers rebuilt that tab a third
time and BOTH anchors vanished, so the parser found neither, and
``build.build_guild`` did what it is designed to do: it fell back to
``config.TRIAL_SKILLS_CURRENT`` behind an on-page "MAY BE STALE" banner. The
banner worked — it is how the breakage was noticed — but the whole site had
meanwhile optimised the wrong four trials for a day, because the fallback is a
hand-edited constant and the real draw had moved on.

The lesson is not "add a third layout". It is that the draw should be read from
the ONE place that is written by the game rather than by a person, and that a
chain of fallbacks across hand-maintained shapes is precisely what let a wrong
draw ship quietly. So:

  * The rebuilt "Trial Assignments" tab is no longer consulted at all. Its own
    row 28 reads "The above table follows the Guild Optimum from
    https://holychikenz.github.io/SCGuildTrials/trials.html" — it is DOWNSTREAM of
    this project's output, which makes it unfit to be an input to it.
  * There is no layout fallback. An unreadable header raises
    :class:`SheetStructureError`, which ``build.build_guild`` still turns into the
    loud stale-draw banner rather than a dead deploy.

CORROBORATION AND ITS LIMITS. ``research/trial-tabs.md`` §2.2 already named this
tab "the more authoritative of the two", and the "Trial Data" results log shows
both guilds drawing the SAME four skills in every cycle on record — which is why
ONE draw (Survey Corps') still serves both guilds. That shared-draw model is the
reason the source tab is fixed at SC's rather than read per guild: on 2026-08-14
the LI tab still held the whole of the 8/10 cycle (its four skills AND both its
combat bosses), i.e. the game had not yet refreshed it. Reading LI's own tab for
LI's draw would therefore have planned this week's trials from last week's roll.
``build.build_guild`` cross-checks each guild's sign-up columns against this draw
and withholds that guild's plan when they disagree, so the staleness is reported
rather than absorbed.

WHAT WAS LOST WITH THE OLD TAB, and it is not this module's doing: the retired
``Trial Priority`` table carried an optional third column holding each trial's
MINIMUM SIGN-UP LEVEL (the lever added in the 2026-08-11 patch). The officers
deleted that table, so the datum no longer exists anywhere on the sheet and
:attr:`TrialDraw.min_levels` is now always empty — every trial unrestricted,
which is exactly the documented rollback state of that feature. Nothing here can
recover it; the officers would have to publish it again somewhere.

Likewise there is no CYCLE DATE on this tab. The old banner carried one and
:attr:`TrialDraw.date` is now always ``""``, which the trials page renders as an
undated draw. The date was carried for logging only and never entered the model.

Skill labels use the trial's own names (``Alchemy``, ``Milking``, ...). Two
differ from the internal trial-skill name and are aliased below:
``Cheesesmithing`` (internal ``C.Smithing``) and ``Bell Farming`` (the member
tab's joke column name for ``Alchemy``, accepted defensively in case the game
ever heads the column that way).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from urllib.parse import quote

from typing import Optional

import requests

from . import config
from .reader import SheetStructureError, _cell


# ---------------------------------------------------------------------------
# Layout constants for the draw source (the game-written sign-up tab)
# ---------------------------------------------------------------------------
# The tab whose header row carries this week's draw. Fixed at Survey Corps'
# because the draw is shared between guilds and SC's tab is the one the game
# keeps current (see the module docstring on the 2026-08-14 LI staleness).
DRAW_TAB = config.DRAW_SOURCE_TAB

# Column 0's sentinel. gviz does NOT error on an unknown tab name — it silently
# serves a *different* tab — so this is the only thing standing between a
# mistyped tab name and a confidently-parsed wrong draw.
USER_SENTINEL = "User"

# The four skilling-trial columns are ALWAYS spreadsheet B–E. Mirrors
# ``signup.SKILLING_COL_START`` / ``SKILLING_COL_COUNT``, which read the
# tick-boxes under these same columns; the two must not drift apart.
SKILLING_COL_START = 1

# The guild draws exactly four skilling trials per cycle (research/trial-tabs.md
# §1 and §2.2). Fail loudly if the sheet ever shows a different count so the
# model is never fed a mis-sized week silently.
EXPECTED_TRIALS = 4

# Sheet-label -> internal trial-skill name. Identity for every skill whose sheet
# label already matches an internal name; only these two differ. Built
# case-insensitively from ``config.TRIAL_SKILL_TO_SHEET_COLUMN`` (the authority
# on which trial-skill names the rest of the pipeline understands).
_SKILL_ALIASES = {
    "cheesesmithing": "C.Smithing",
    # The member tab calls the Alchemy column "Bell Farming". The game heads the
    # SIGN-UP column "Alchemy", so this alias should never fire — it is here so
    # that if the game ever switches to the sheet's own label, the draw keeps
    # reading rather than failing on a name we already understand.
    "bellfarming": "Alchemy",
    "bell farming": "Alchemy",
}
_KNOWN_SKILLS = {
    name.lower(): name for name in config.TRIAL_SKILL_TO_SHEET_COLUMN
}


@dataclass
class TrialDraw:
    """This week's skilling-trial draw, read from the sheet.

    ``skills`` are the internal trial-skill names in the order the GAME lists
    them across columns B–E, which also drives sign-up lock precedence in
    :func:`src.signup.plan`. Note that this order is no longer a PRIORITY: the
    retired ``Trial Priority`` table ranked the four trials 1–4 and the current
    source carries no such ranking, so the order is the sheet's column order and
    means nothing beyond it.

    ``date`` is always ``""`` — the draw source carries no cycle date (see the
    module docstring). Retained so callers and the rendered page need not change.

    ``min_levels`` maps a trial skill to the minimum sign-up level the officers
    have set for it, or to ``None`` where they have set none. Always empty from
    this source, the datum having gone with the old tab; a skill absent from the
    map is unrestricted, so the constraint simply does not exist until somebody
    publishes it again.
    """

    skills: list[str]
    date: str
    min_levels: dict[str, Optional[int]] = field(default_factory=dict)


def _normalise_skill(raw: str, column: int) -> str:
    """Map a sheet skill label to its internal trial-skill name.

    Raises:
        SheetStructureError: if the label is not a recognised trial skill (a
            typo, a new skill, a combat boss that has drifted left into the
            skilling block, or the wrong tab served by gviz).
    """
    key = raw.strip().lower()
    name = _SKILL_ALIASES.get(key) or _KNOWN_SKILLS.get(key)
    if name is None:
        raise SheetStructureError(
            f"{DRAW_TAB!r} column {column} (spreadsheet "
            f"{chr(ord('A') + column)}) has header {raw!r}, which is not a "
            f"recognised skilling trial. Columns B–E must be this week's four "
            f"skilling trials. Known trial skills: "
            f"{sorted(config.TRIAL_SKILL_TO_SHEET_COLUMN)}. The tab layout may "
            "have changed, or gviz served a different tab."
        )
    return name


def fetch_draw_csv(tab_name: str = DRAW_TAB) -> str:
    """Fetch the draw source tab's gviz CSV export, addressed by name.

    Note what is NOT passed here, in deliberate contrast to the retired
    ``Trial Assignments`` fetch: no ``&headers=0`` override. That override
    existed to stop gviz swallowing the old tab's banner rows into its guessed
    header row when the officers wrote prose above the table. Here the header row
    is exactly what we want, and gviz's default behaviour hands it to us as the
    CSV's first line — the same request :func:`src.signup.fetch_signup_csv`
    makes, so the draw and the tick-boxes are read from an identically-shaped
    response.

    Raises:
        RuntimeError: on 401/403 (sharing revoked) or other HTTP/network errors.
    """
    url = config.GVIZ_URL.format(sheet=quote(tab_name))
    try:
        resp = requests.get(url, timeout=config.FETCH_TIMEOUT)
    except requests.RequestException as exc:  # network-level failure
        raise RuntimeError(
            f"Failed to reach Google Sheets gviz endpoint: {exc}"
        ) from exc

    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"Google Sheets returned {resp.status_code} for the gviz export of "
            f"tab {tab_name!r}. The sheet's 'anyone with the link' sharing may "
            f"have been revoked. URL: {url}"
        )

    resp.raise_for_status()
    return resp.text


def trial_columns(csv_text: str, tab_label: str = DRAW_TAB) -> list[str]:
    """Return the four skilling-trial skills a sign-up tab's header declares.

    The shared primitive behind both :func:`parse_draw` (which reads the DRAW
    from Survey Corps' tab) and ``build.build_guild``'s staleness cross-check
    (which reads each guild's OWN tab and compares). Returning internal
    trial-skill names rather than sheet columns keeps both callers in one
    namespace.

    ``tab_label`` names the tab in any error so a failure reads e.g.
    "'LI Trial Signup' column 1 ..." — it has no effect on parsing.

    Raises:
        SheetStructureError: if the CSV is empty, column 0 is not the ``User``
            sentinel (gviz served a different tab), the row is too short to hold
            columns B–E, or any of those four carries an unrecognised label.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise SheetStructureError(
            f"{tab_label!r} CSV was empty; cannot read the draw from its header "
            "row."
        )

    header = rows[0]
    if USER_SENTINEL not in _cell(header, 0):
        raise SheetStructureError(
            f"{tab_label!r} header did not match: expected column 0 to contain "
            f"{USER_SENTINEL!r}, got {_cell(header, 0)!r}. The tab may not exist "
            "(gviz silently serves a different tab in that case) or the layout "
            f"changed. Inspect the {tab_label!r} tab before this can run again."
        )

    end = SKILLING_COL_START + EXPECTED_TRIALS  # first column past the block
    if len(header) < end:
        raise SheetStructureError(
            f"{tab_label!r} has too few columns: expected {USER_SENTINEL!r} plus "
            f"the four skilling trials in columns B–E (>= {end} columns), got "
            f"{len(header)}: {header!r}. The tab layout changed or gviz served a "
            f"different tab. Inspect the {tab_label!r} tab before rerunning."
        )

    return [
        _normalise_skill(_cell(header, idx), idx)
        for idx in range(SKILLING_COL_START, end)
    ]


def parse_draw(csv_text: str) -> TrialDraw:
    """Parse the draw source CSV into this week's :class:`TrialDraw`.

    Raises:
        SheetStructureError: on anything :func:`trial_columns` rejects. There is
            no second layout to fall back to, by design — see the module
            docstring on why the old fallback chain was the problem rather than
            the safety net.
    """
    return TrialDraw(
        skills=trial_columns(csv_text, DRAW_TAB),
        # This source carries no cycle date and no minimum-level column.
        date="",
        min_levels={},
    )


def load_draw(tab_name: str = DRAW_TAB) -> TrialDraw:
    """Fetch and parse this week's skilling-trial draw from the sheet."""
    return parse_draw(fetch_draw_csv(tab_name))
