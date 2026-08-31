"""Fetch and parse a guild's scripted "Roster" tab.

A SECOND source of per-member data, written by the standalone
``profiles-endpoint`` Apps Script from a per-character harvest: one row per
member, 78 columns, one clean header row. It carries, per member and per skill,
the three things the hand-maintained member tab carries (level, house level,
tool) plus the one it cannot express — the tool's ENHANCEMENT level — and the
five per-member purchased shrine levels.

WHY THIS IS ITS OWN MODULE, and not an addition to ``scraper.py``.
``scraper.py`` is written top to bottom against ONE table shape: 58 columns, ten
five-column skill blocks at a fixed stride, positional offsets, sentinels by
column index. The roster tab shares none of it — 78 columns, header-name
addressing, and a column order that legitimately VARIES upstream. Merging the two
would give one module two column models and two structure guards with
contradictory rules ("match by index/substring" against "match by exact name").
``draw.py``, ``signup.py`` and ``scraper.py`` each read one tab shape and each
carries its own guard; this is the fourth, by the same rule.

WHAT IT MUST NOT DO is duplicate the network path. ``scraper.fetch_tab_csv`` is
already parametrised by tab name, already url-encodes, and already carries the
401/403 message about revoked sharing. There is exactly one place in this
repository that talks to gviz and it stays that way.

No credentials, no Google writes: this reads the publicly-exported CSV only.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Optional

from . import config
from .reader import SheetStructureError
from .scraper import fetch_tab_csv


@dataclass
class RosterRow:
    """One member's harvested row, keyed throughout by ``config.SKILLS`` name.

    Every per-skill mapping is total over ``config.SKILLS`` and every value is
    ``Optional``: ``None`` means "the roster did not say", which is NOT the same
    as zero. The endpoint preserves that distinction deliberately — ``0`` is a
    catalogue item the member never acquired, blank is a value withheld
    (``hideWearableItems``) or unknown — and a merge that collapsed the two would
    price nine SC members' hidden gear as no gear at all.
    """

    name: str
    character_id: str
    captured_at: str
    revision: str
    levels: dict[str, Optional[int]] = field(default_factory=dict)
    houses: dict[str, Optional[int]] = field(default_factory=dict)
    tools: dict[str, Optional[str]] = field(default_factory=dict)
    tool_enh: dict[str, Optional[int]] = field(default_factory=dict)
    # shrine key (config.GUILD_SHRINE_SKILLING_BUFFS) -> the member's OWN
    # purchased skilling level, or None where the column was blank.
    shrines: dict[str, Optional[int]] = field(default_factory=dict)


def fetch_roster_csv(tab_name: str) -> str:
    """Fetch a roster tab's gviz CSV, by tab name.

    One line, on purpose: it reuses ``scraper.fetch_tab_csv`` rather than
    repeating the URL formatting, the timeout and the revoked-sharing message.

    NOTE the parameter this deliberately does NOT pass.
    ``config.GVIZ_NO_HEADER_COLLAPSE`` ("&headers=0") is the recorded remedy for
    gviz swallowing data rows into its guessed header. It must never be appended
    here: the roster tab has a single clean header row, and with the override on
    gviz blanks the label of every NUMERIC column — which is most of this tab, so
    the header guard below would then fail on almost every name it looks for.
    Verified live 2026-08-31.
    """
    return fetch_tab_csv(tab_name)


def required_columns() -> list[str]:
    """Every column name the parser will read, in a stable order.

    Derived from ``config.ROSTER_COLUMNS`` and
    ``config.ROSTER_SINGLETON_COLUMNS`` so the guard and the parser can never
    disagree about what the tab must contain.
    """
    names: list[str] = list(config.ROSTER_SINGLETON_COLUMNS)
    for skill in config.SKILLS:
        level, house, tool = config.ROSTER_COLUMNS[skill]
        names.extend([level, house, tool, tool + config.ROSTER_TOOL_ENH_SUFFIX])
    return names


def _index_header(header: list[str]) -> dict[str, int]:
    """``{column name: 0-based index}`` from the header row.

    Cells are stripped; a duplicated name keeps its FIRST occurrence, which is
    the one a positional reader would have found too.
    """
    index: dict[str, int] = {}
    for i, cell in enumerate(header):
        name = cell.strip()
        if name and name not in index:
            index[name] = i
    return index


def _validate_header(header: list[str]) -> dict[str, int]:
    """Require every column the parser reads, BY EXACT NAME. Return the index.

    Extra columns are allowed and ignored — the upstream module's ``stableGear``
    toggle adds fourteen of them, and a toggle nobody in this repository controls
    must not break the build. A MISSING or RENAMED column is a structure change
    and fails loudly, naming every column it could not find, in the style
    ``scraper._validate_gviz_header`` uses.

    Loud here does not mean fatal: ``build._fetch_guild`` catches this and
    degrades to the manual tab behind a banner (the roster tab is written by a
    SEPARATE deployment whose header shifts when a module toggle moves, and SC is
    ``required=True``, so an uncaught raise would take down every page of both
    guilds). The failure is still reported; it just does not stop the deploy.
    """
    index = _index_header(header)
    missing = [name for name in required_columns() if name not in index]
    if missing:
        raise SheetStructureError(
            "Roster tab header did not carry every expected column. The tab may "
            "not exist (gviz silently serves a different tab in that case), the "
            "upstream profiles endpoint may have changed its column set, or a "
            "module toggle may have been moved. Missing:\n  - "
            + "\n  - ".join(missing)
            + "\nInspect the tab and update config.ROSTER_COLUMNS / "
            "config.ROSTER_SINGLETON_COLUMNS before the roster can be read again."
        )
    return index


def _to_int_strict(value: str, column: str, name: str) -> Optional[int]:
    """Blank -> None, a numeral -> int, ANYTHING ELSE -> SheetStructureError.

    Deliberately NOT ``reader._to_int``, which returns None for both a blank and
    a garbage cell. That tolerance is right for a hand-maintained tab, where a
    stray keystroke should cost one cell rather than the build; it is wrong here,
    because it would erase the blank/zero distinction this tab exists to
    preserve. A non-numeric cell on a MACHINE-written tab is a structure problem,
    not an officer's typo.
    """
    value = value.strip()
    if value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise SheetStructureError(
            f"Roster column {column!r} held a non-numeric value {value!r} for "
            f"member {name!r}. This tab is machine-written, so a non-numeric "
            f"cell means its format changed rather than that someone mistyped."
        ) from exc


def _cell(row: list[str], idx: int) -> str:
    """Safely read a cell, returning '' if the row is short."""
    return row[idx].strip() if idx < len(row) else ""


def parse(csv_text: str) -> list[RosterRow]:
    """Parse roster CSV text into ``RosterRow`` records.

    The header is line 1 and data begins on line 2. Rows are read until the
    first blank ``name`` cell. Every column is addressed through the validated
    ``{name: index}`` map, so a reordering of the tool block — which the upstream
    module does legitimately produce — parses identically.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise SheetStructureError("Roster CSV was empty; cannot locate header row.")

    index = _validate_header(rows[0])
    col = index.__getitem__

    out: list[RosterRow] = []
    for raw in rows[1:]:
        name = _cell(raw, col("name"))
        if name == "":
            break  # first blank name cell marks the end of the roster

        levels: dict[str, Optional[int]] = {}
        houses: dict[str, Optional[int]] = {}
        tools: dict[str, Optional[str]] = {}
        tool_enh: dict[str, Optional[int]] = {}
        for skill in config.SKILLS:
            lv_col, house_col, tool_col = config.ROSTER_COLUMNS[skill]
            enh_col = tool_col + config.ROSTER_TOOL_ENH_SUFFIX
            levels[skill] = _to_int_strict(_cell(raw, col(lv_col)), lv_col, name)
            houses[skill] = _to_int_strict(_cell(raw, col(house_col)), house_col, name)
            item = _cell(raw, col(tool_col))
            tools[skill] = item or None
            tool_enh[skill] = _to_int_strict(_cell(raw, col(enh_col)), enh_col, name)

        shrines: dict[str, Optional[int]] = {}
        for shrine_col, key in config.ROSTER_SHRINE_COLUMNS.items():
            shrines[key] = _to_int_strict(_cell(raw, col(shrine_col)), shrine_col, name)

        out.append(
            RosterRow(
                name=name,
                character_id=_cell(raw, col("characterId")),
                captured_at=_cell(raw, col("capturedAt")),
                revision=_cell(raw, col("revision")),
                levels=levels,
                houses=houses,
                tools=tools,
                tool_enh=tool_enh,
                shrines=shrines,
            )
        )

    return out


def scrape_roster_tab(tab_name: str) -> list[RosterRow]:
    """Fetch, guard and parse a named roster tab.

    Raises:
        SheetStructureError: if the tab does not carry the expected column set
            (wrong tab served, tab missing, or the upstream layout changed).
        RuntimeError: on fetch/HTTP failure.
    """
    return parse(fetch_roster_csv(tab_name))
