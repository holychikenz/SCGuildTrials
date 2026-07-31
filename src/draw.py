"""Read this week's skilling-trial draw from the guild sheet.

The four skilling trials the guild runs each cycle are NOT a code constant —
they are drawn (seemingly randomly) each cycle and published by the officers in
the **"Trial Assignments"** tab. The officers have published it in two shapes;
this module reads BOTH, because the tab has already been rebuilt under us once.

CURRENT layout (since the 2026-07-31 rebuild) — a two-column ``Trial Priority``
table, skill in the banner's own column and the priority number beside it. There
are no ``Trial N`` slot labels any more, and the skilling section carries no date
of its own (only the ``Combat Trials`` block below it does)::

                                          Trial Priority
                                          Milking          3
                                          Foraging         4
                                          Crafting         2
                                          Alchemy          1

LEGACY layout (up to 2026-07-25) — a ``Skilling Trial Info`` banner with one
``Trial N`` row per drawn skill::

    Skilling Trial Info   Date: 7/24        Priority
    Trial 1               Milking           4
    Trial 2               Woodcutting       3
    Trial 3               Crafting          2
    Trial 4               Alchemy           1
    Priority goes from 1 to 4, with 1 being the highest

This module fetches that tab (the anonymous gviz CSV export, exactly like
:mod:`src.scraper` and :mod:`src.signup`) and returns the drawn skills in the
order the officers list them. ``build.py`` threads the result into
``trials.run_week`` and ``signup.plan`` so the published site always reflects the
*current* draw rather than a hand-transcribed constant that goes stale the moment
the officers reroll.

``config.TRIAL_SKILLS_CURRENT`` remains only as an offline fallback/default for
tests and direct library calls; the live build reads the sheet.

Skill labels in the sheet use the trial's own names (``Alchemy``, ``Milking``,
...). The one label that differs from the internal trial-skill name is
``Cheesesmithing`` (internal ``C.Smithing``); it is aliased below. Parsing is
anchored on the ``Skilling Trial Info`` / ``Trial Priority`` sentinels — gviz
silently serves a *different* tab on a bad name, so an unrecognised layout must
fail loudly rather than emit a stale/guessed draw (the whole point of reading it
live).

INDEPENDENT CORROBORATION: each guild's sign-up tab ("SC Trial Signup" /
"LI Trial Signup") heads its four tick-box columns with the same four skills,
written by the game itself. If this parser and those headers ever disagree, the
sign-up headers are the more authoritative of the two — see
``research/trial-tabs.md`` §2.2.

The tab is fetched with gviz's header-collapsing turned OFF
(``config.GVIZ_NO_HEADER_COLLAPSE``); see :func:`fetch_assignments_csv` for why
that is not optional. ``build.build_guild`` catches a structure failure here and
degrades to the last-known draw behind a loud on-page warning rather than felling
the whole deploy — loud, but no longer fatal.
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

# LEGACY anchor (tab layout up to 2026-07-25). The draw lived under a row whose
# column 1 is exactly this banner; the date sat in column 2 ("Date: 7/24") and
# the drawn skills in the "Trial N" rows immediately below (skill in col 2,
# priority in col 4). The COMBAT section uses a distinct banner ("Combat Trail
# Info"), so anchoring on this exact string keeps the two apart.
SKILLING_SECTION = "Skilling Trial Info"

# CURRENT anchor (tab layout since 2026-07-31). The draw is a two-column table
# headed by exactly this string; the drawn skills run down the banner's OWN
# column and the priority numbers sit in the column to its right. Its column is
# NOT fixed (it sits at col 10 today, to the right of the cut-off tables), so it
# is located by scanning every column rather than pinned by index — the officers
# have already moved this block once. The combat block's own priority column is
# headed plain "Priority", so this two-word string keeps the two apart.
PRIORITY_SECTION = "Trial Priority"

# The col-1 label of a drawn-trial row in the LEGACY layout, e.g. "Trial 1".
_TRIAL_ROW = re.compile(r"Trial\s+\d+", re.IGNORECASE)

# A cycle-date cell, e.g. "Date: 7/31". Since the 2026-07-31 rebuild the skilling
# section has no date of its own, so the tab's single date (published on the
# "Combat Trials" banner) is used as the cycle date; it is carried for logging
# only and both sections are drawn for the same weekly cycle.
_DATE_CELL = re.compile(r"Date\s*:\s*(.+)", re.IGNORECASE)

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

    Requests ``&headers=0`` (``config.GVIZ_NO_HEADER_COLLAPSE``) so gviz returns
    every row as DATA instead of guessing how many leading rows are header
    labels. That guess grows with whatever the officers write above the table:
    on 2026-07-25 a new 16-row notice pushed the ``Skilling Trial Info`` banner
    and all four draw rows inside gviz's header row, where the parser could not
    see them, and the deploy died. With the override the parser reads the sheet's
    true row layout and is immune to text added above it.

    Raises:
        RuntimeError: on 401/403 (sharing revoked) or other HTTP/network errors.
    """
    url = config.GVIZ_URL.format(sheet=quote(tab_name)) + (
        config.GVIZ_NO_HEADER_COLLAPSE
    )
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


def _parse_legacy_block(
    rows: list[list[str]],
) -> tuple[str, list[str], str] | None:
    """Read the LEGACY ``Skilling Trial Info`` block, or ``None`` if absent.

    Locates the banner (col 1), reads the cycle date (col 2), then collects the
    contiguous ``Trial N`` rows below it (skill in col 2), stopping at the first
    non-trial row (e.g. the "Priority goes from 1 to 4" note) — which keeps the
    combat section out.

    Returns:
        ``(section_name, skills, date_cell)``, or ``None`` if the banner is not
        on the tab at all.
    """
    header_idx = None
    date_cell = ""
    for i, row in enumerate(rows):
        if _cell(row, 1) == SKILLING_SECTION:
            header_idx = i
            date_cell = _cell(row, 2)
            break

    if header_idx is None:
        return None

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

    return SKILLING_SECTION, skills, date_cell


def _parse_priority_block(
    rows: list[list[str]],
) -> tuple[str, list[str], str] | None:
    """Read the CURRENT ``Trial Priority`` block, or ``None`` if absent.

    Scans every column for the banner (its column is not fixed), then walks down
    that same column collecting drawn skills. A blank cell ends the block, which
    is what separates the four skills from the sign-up prose printed below them;
    a blank cell BEFORE the first skill is tolerated as a spacer. A non-blank,
    unrecognised cell raises via :func:`_normalise_skill` rather than being
    skipped — a renamed or mis-typed skill must be loud, never guessed past.

    The block carries no date (the tab publishes one cycle date, on the combat
    banner), so the returned date cell is empty and :func:`parse_draw` falls back
    to the tab-wide scan.

    Returns:
        ``(section_name, skills, "")``, or ``None`` if the banner is not on the
        tab at all.
    """
    header = None
    for i, row in enumerate(rows):
        for col, cell in enumerate(row):
            if cell.strip() == PRIORITY_SECTION:
                header = (i, col)
                break
        if header is not None:
            break

    if header is None:
        return None

    header_idx, col = header
    skills: list[str] = []
    for row in rows[header_idx + 1:]:
        label = _cell(row, col)
        if label == "":
            if skills:
                break  # end of the drawn-trials block
            continue  # tolerate a blank spacer between banner and first skill
        skills.append(_normalise_skill(label))

    return PRIORITY_SECTION, skills, ""


def _find_cycle_date(rows: list[list[str]]) -> str:
    """Return the tab's first ``Date: …`` value, or ``""`` if it has none."""
    for row in rows:
        for cell in row:
            match = _DATE_CELL.fullmatch(cell.strip())
            if match:
                return match.group(1).strip()
    return ""


def parse_draw(csv_text: str) -> TrialDraw:
    """Parse the Trial Assignments CSV into this week's :class:`TrialDraw`.

    Tries the LEGACY ``Skilling Trial Info`` block first and falls back to the
    CURRENT ``Trial Priority`` table (see the module docstring for both shapes).
    Legacy wins when both are present because it carries explicit ``Trial N``
    slot labels — strictly more information than the priority table.

    Raises:
        SheetStructureError: if neither anchor is present, no drawn trials are
            found, the count is not :data:`EXPECTED_TRIALS`, or a skill label is
            unrecognised (any of these means the wrong tab or a layout change).
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise SheetStructureError(
            f"{ASSIGNMENTS_TAB!r} CSV was empty; cannot locate the "
            f"{SKILLING_SECTION!r} or {PRIORITY_SECTION!r} section."
        )

    # Try the anchors in order of information content: the legacy block carries
    # explicit "Trial N" slot labels, the priority table does not. An anchor that
    # is PRESENT but yields no skills (an emptied or repurposed block) must not
    # shadow the other one — it is only remembered so the count error below names
    # the right section.
    found = None
    for _parse in (_parse_legacy_block, _parse_priority_block):
        candidate = _parse(rows)
        if candidate is None:
            continue
        if candidate[1]:
            found = candidate
            break
        found = found or candidate

    if found is None:
        raise SheetStructureError(
            f"Could not find the {SKILLING_SECTION!r} banner (column 1) or the "
            f"{PRIORITY_SECTION!r} table (any column) in the "
            f"{ASSIGNMENTS_TAB!r} tab. The tab may not exist (gviz silently "
            "serves a different tab in that case) or its layout changed again. "
            "Inspect the tab before this can run again; each guild's sign-up "
            "tab heads its four tick-box columns with the same four skills and "
            "can be used to confirm the draw by hand."
        )

    section, skills, date_cell = found
    if len(skills) != EXPECTED_TRIALS:
        raise SheetStructureError(
            f"Expected {EXPECTED_TRIALS} skilling trials under {section!r} in "
            f"the {ASSIGNMENTS_TAB!r} tab, found {len(skills)}: {skills}. The "
            "tab layout may have changed."
        )

    # "Date: 7/24" -> "7/24"; tolerate extra whitespace and a missing prefix.
    # The priority table has no date of its own, so fall back to the tab's.
    date = date_cell.split(":", 1)[1].strip() if ":" in date_cell else date_cell.strip()
    return TrialDraw(skills=skills, date=date or _find_cycle_date(rows))


def load_draw(tab_name: str = ASSIGNMENTS_TAB) -> TrialDraw:
    """Fetch and parse this week's skilling-trial draw from the sheet."""
    return parse_draw(fetch_assignments_csv(tab_name))
