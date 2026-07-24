"""Read this week's skilling-trial draw from the guild sheet.

The four skilling trials the guild runs each cycle are NOT a code constant —
they are drawn (seemingly randomly) each cycle and published by the officers in
the **"Trial Assignments"** tab, under the ``Skilling Trial Info`` banner::

    Skilling Trial Info   Date: 7/24        Priority
    Trial 1               Milking           4
    Trial 2               Woodcutting       3
    Trial 3               Crafting          2
    Trial 4               Alchemy           1
    Priority goes from 1 to 4, with 1 being the highest

This module fetches that tab (the anonymous gviz CSV export, exactly like
:mod:`src.scraper` and :mod:`src.signup`) and returns the drawn skills in
Trial 1..N order. ``build.py`` threads the result into ``trials.run_week`` and
``signup.plan`` so the published site always reflects the *current* draw rather
than a hand-transcribed constant that goes stale the moment the officers reroll.

``config.TRIAL_SKILLS_CURRENT`` remains only as an offline fallback/default for
tests and direct library calls; the live build reads the sheet.

Skill labels in the sheet use the trial's own names (``Alchemy``, ``Milking``,
...). The one label that differs from the internal trial-skill name is
``Cheesesmithing`` (internal ``C.Smithing``); it is aliased below. Parsing is
anchored on the ``Skilling Trial Info`` sentinel — gviz silently serves a
*different* tab on a bad name, so an unrecognised layout must fail loudly rather
than emit a stale/guessed draw (the whole point of reading it live).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from urllib.parse import quote

import requests

from . import config
from .reader import SheetStructureError, _cell


# ---------------------------------------------------------------------------
# Layout constants for the "Trial Assignments" tab
# ---------------------------------------------------------------------------
ASSIGNMENTS_TAB = "Trial Assignments"

# The skilling-trial draw lives under a row whose column 1 is exactly this
# banner; the date sits in column 2 ("Date: 7/24") and the drawn skills in the
# "Trial N" rows immediately below (skill in col 2, priority in col 4). The
# COMBAT section uses a distinct banner ("Combat Trail Info"), so anchoring on
# this exact string keeps the two apart.
SKILLING_SECTION = "Skilling Trial Info"

# The col-1 label of a drawn-trial row, e.g. "Trial 1".
_TRIAL_ROW = re.compile(r"Trial\s+\d+", re.IGNORECASE)

# The guild draws exactly four skilling trials per cycle (research/trial-tabs.md
# §1 and §2.2). Fail loudly if the sheet ever shows a different count so the
# model is never fed a mis-sized week silently.
EXPECTED_TRIALS = 4

# Sheet-label -> internal trial-skill name. Identity for every skill whose sheet
# label already matches an internal name; only Cheesesmithing differs. Built
# case-insensitively from ``config.TRIAL_SKILL_TO_SHEET_COLUMN`` (the authority
# on which trial-skill names the rest of the pipeline understands).
_SKILL_ALIASES = {"cheesesmithing": "C.Smithing"}
_KNOWN_SKILLS = {
    name.lower(): name for name in config.TRIAL_SKILL_TO_SHEET_COLUMN
}


@dataclass
class TrialDraw:
    """This week's skilling-trial draw, read from the sheet.

    ``skills`` are the internal trial-skill names in Trial 1..N order (the same
    order the officers list them, which also drives sign-up lock precedence in
    :func:`src.signup.plan`). ``date`` is the cycle date as published on the tab
    (e.g. ``"7/24"``), carried for logging only.
    """

    skills: list[str]
    date: str


def _normalise_skill(raw: str) -> str:
    """Map a sheet skill label to its internal trial-skill name.

    Raises:
        SheetStructureError: if the label is not a recognised trial skill (a
            typo, a new skill, or the wrong tab served by gviz).
    """
    key = raw.strip().lower()
    name = _SKILL_ALIASES.get(key) or _KNOWN_SKILLS.get(key)
    if name is None:
        raise SheetStructureError(
            f"Unrecognised skilling-trial skill {raw!r} in the "
            f"{ASSIGNMENTS_TAB!r} tab. Known trial skills: "
            f"{sorted(config.TRIAL_SKILL_TO_SHEET_COLUMN)}. The tab layout may "
            "have changed, or gviz served a different tab."
        )
    return name


def fetch_assignments_csv(tab_name: str = ASSIGNMENTS_TAB) -> str:
    """Fetch the Trial Assignments tab's gviz CSV export, addressed by name.

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


def parse_draw(csv_text: str) -> TrialDraw:
    """Parse the Trial Assignments CSV into this week's :class:`TrialDraw`.

    Locates the ``Skilling Trial Info`` banner (col 1), reads the cycle date
    (col 2), then collects the contiguous ``Trial N`` rows below it (skill in
    col 2), stopping at the first non-trial row (e.g. the "Priority goes from
    1 to 4" note) — which keeps the combat section out.

    Raises:
        SheetStructureError: if the banner is missing, no drawn trials are
            found, the count is not :data:`EXPECTED_TRIALS`, or a skill label is
            unrecognised (any of these means the wrong tab or a layout change).
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise SheetStructureError(
            f"{ASSIGNMENTS_TAB!r} CSV was empty; cannot locate the "
            f"{SKILLING_SECTION!r} section."
        )

    header_idx = None
    date_cell = ""
    for i, row in enumerate(rows):
        if _cell(row, 1) == SKILLING_SECTION:
            header_idx = i
            date_cell = _cell(row, 2)
            break

    if header_idx is None:
        raise SheetStructureError(
            f"Could not find the {SKILLING_SECTION!r} banner in the "
            f"{ASSIGNMENTS_TAB!r} tab (expected in column 1). The tab may not "
            "exist (gviz silently serves a different tab in that case) or its "
            "layout changed. Inspect the tab before this can run again."
        )

    skills: list[str] = []
    for row in rows[header_idx + 1:]:
        label = _cell(row, 1)
        if _TRIAL_ROW.fullmatch(label):
            skills.append(_normalise_skill(_cell(row, 2)))
            continue
        if skills:
            break  # end of the drawn-trials block
        if label == "":
            continue  # tolerate a blank spacer between banner and Trial 1
        break  # some other content directly under the banner -> no draw found

    if len(skills) != EXPECTED_TRIALS:
        raise SheetStructureError(
            f"Expected {EXPECTED_TRIALS} skilling trials under "
            f"{SKILLING_SECTION!r} in the {ASSIGNMENTS_TAB!r} tab, found "
            f"{len(skills)}: {skills}. The tab layout may have changed."
        )

    # "Date: 7/24" -> "7/24"; tolerate extra whitespace and a missing prefix.
    date = date_cell.split(":", 1)[1].strip() if ":" in date_cell else date_cell.strip()
    return TrialDraw(skills=skills, date=date)


def load_draw(tab_name: str = ASSIGNMENTS_TAB) -> TrialDraw:
    """Fetch and parse this week's skilling-trial draw from the sheet."""
    return parse_draw(fetch_assignments_csv(tab_name))
