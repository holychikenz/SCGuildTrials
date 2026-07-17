"""Fetch and parse the guild skill-register CSV.

No credentials, no Google writes: this reads the publicly-exported CSV only.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Optional

import requests

from . import config


class SheetStructureError(Exception):
    """Raised when the sheet no longer matches the expected layout.

    Propagating this out of ``build.py`` makes the GitHub Action exit non-zero
    so the failure is loud rather than silently producing a broken page.
    """


@dataclass
class SkillEntry:
    """One member's standing in one skill."""

    level: Optional[int]
    tool: bool
    top: bool
    bot: bool


@dataclass
class MemberRow:
    """A single guild member's parsed row."""

    name: str
    main_classes: str
    flex: str
    flex_levels: list[Optional[int]] = field(default_factory=list)
    skills: dict[str, SkillEntry] = field(default_factory=dict)


def fetch_csv() -> str:
    """Fetch the published CSV export as text.

    Raises:
        RuntimeError: on 401/403 (sheet sharing likely revoked) or other
            HTTP errors, with a message pointing at the likely cause.
    """
    try:
        resp = requests.get(config.CSV_URL, timeout=config.FETCH_TIMEOUT)
    except requests.RequestException as exc:  # network-level failure
        raise RuntimeError(f"Failed to reach Google Sheets export: {exc}") from exc

    if resp.status_code in (401, 403):
        raise RuntimeError(
            "Google Sheets returned "
            f"{resp.status_code} for the CSV export. The sheet's "
            "'anyone with the link' sharing may have been revoked. "
            f"URL: {config.CSV_URL}"
        )

    resp.raise_for_status()
    return resp.text


def _cell(row: list[str], idx: int) -> str:
    """Safely read a cell, returning '' if the row is short."""
    return row[idx].strip() if idx < len(row) else ""


def _to_int(value: str) -> Optional[int]:
    """Coerce a numeric string to int; blank -> None."""
    value = value.strip()
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        # Tolerate stray non-numeric level cells rather than crashing.
        return None


def _to_bool(value: str) -> bool:
    """Literal 'TRUE' -> True, everything else (incl. blank/'FALSE') -> False."""
    return value.strip().upper() == "TRUE"


def _validate_header(rows: list[list[str]]) -> None:
    """Check the real header row against sentinel columns."""
    if len(rows) <= config.HEADER_ROW_INDEX:
        raise SheetStructureError(
            "CSV has too few rows to contain the expected header row "
            f"(need > {config.HEADER_ROW_INDEX}, got {len(rows)})."
        )

    header = rows[config.HEADER_ROW_INDEX]
    mismatches = []
    for col, expected in config.SENTINEL_HEADERS.items():
        actual = _cell(header, col)
        if actual != expected:
            mismatches.append(f"col {col}: expected {expected!r}, got {actual!r}")

    if mismatches:
        raise SheetStructureError(
            "Guild sheet structure has changed; the column map in config.py "
            "no longer matches the header row. Mismatches:\n  - "
            + "\n  - ".join(mismatches)
            + "\nInspect the CSV and update config.SENTINEL_HEADERS / column "
            "offsets before this pipeline can run again."
        )


def parse(csv_text: str) -> list[MemberRow]:
    """Parse the CSV text into a list of ``MemberRow``.

    Skips the two note rows, validates the header, then reads member rows
    until the first empty Member cell.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    _validate_header(rows)

    members: list[MemberRow] = []
    for row in rows[config.FIRST_DATA_ROW_INDEX :]:
        name = _cell(row, config.COL_NAME)
        if name == "":
            # First blank Member cell marks the end of the member list.
            break

        flex_levels = [_to_int(_cell(row, c)) for c in config.FLEX_LEVEL_COLS]

        skills: dict[str, SkillEntry] = {}
        for i, skill_name in enumerate(config.SKILLS):
            base = config.SKILL_BLOCK_START + i * config.SKILL_BLOCK_STRIDE
            skills[skill_name] = SkillEntry(
                level=_to_int(_cell(row, base + config.SKILL_LEVEL_OFFSET)),
                tool=_to_bool(_cell(row, base + config.SKILL_TOOL_OFFSET)),
                top=_to_bool(_cell(row, base + config.SKILL_TOP_OFFSET)),
                bot=_to_bool(_cell(row, base + config.SKILL_BOT_OFFSET)),
            )

        members.append(
            MemberRow(
                name=name,
                main_classes=_cell(row, config.COL_MAIN_CLASSES),
                flex=_cell(row, config.COL_FLEX),
                flex_levels=flex_levels,
                skills=skills,
            )
        )

    return members
