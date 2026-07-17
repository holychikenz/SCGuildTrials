"""Fetch and parse a named guild member tab via the gviz CSV endpoint.

The gviz endpoint (``.../gviz/tq?tqx=out:csv&sheet=<name>``) lets us pull a tab
by name rather than by gid. Two things differ from the ``export?format=csv``
path used by ``reader.py``:

  1. gviz collapses the sheet's three header rows into ONE merged, fully-quoted
     header row (data begins on line 2). Some header cells carry merged junk
     text prepended and/or trailing spaces (e.g. Milking's header reads
     "Tool is for Celestial Milking ").
  2. gviz appends trailing "summary" columns after the real member table, so
     each row is sliced to the known column range before parsing.

CRITICAL GOTCHA: gviz does NOT error on an unknown/misspelled sheet name -- it
silently serves a *different* tab. The header guard below is therefore
mandatory; without it a bad tab name would emit garbage rather than fail.

No credentials, no Google writes: this reads the publicly-exported CSV only.
It reuses the coercion helpers, dataclasses, and structure-error type from
``reader.py`` rather than duplicating that logic.
"""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from . import config
from .reader import (
    MemberRow,
    SheetStructureError,
    SkillEntry,
    _cell,
    _to_bool,
    _to_int,
)


@dataclass
class GuildData:
    """A parsed member tab wrapped with fetch metadata for JSON output."""

    tab: str
    fetched_at: str  # UTC ISO-8601 timestamp
    member_count: int
    members: list[MemberRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Produce a JSON-serializable dict.

        Members are serialized with ``dataclasses.asdict`` (recursively
        flattening the nested ``SkillEntry`` values), matching the member
        shape written to ``_site/data.json`` by the existing pipeline.
        """
        return {
            "tab": self.tab,
            "fetched_at": self.fetched_at,
            "member_count": self.member_count,
            "members": [asdict(m) for m in self.members],
        }


def fetch_tab_csv(tab_name: str) -> str:
    """Fetch a tab's gviz CSV export as text, addressed by tab name.

    Raises:
        RuntimeError: on 401/403 (sheet sharing likely revoked) or other
            HTTP/network errors, with a message pointing at the likely cause.
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


def _validate_gviz_header(header: list[str]) -> None:
    """Guard against gviz silently serving the wrong tab.

    Matches the single collapsed header row against member-table sentinels.
    Sentinel cells may carry merged junk text and trailing spaces, so matching
    is by substring containment (after strip) unless the mode is "equals".
    """
    mismatches = []
    for col, (mode, expected) in config.GVIZ_SENTINEL_HEADERS.items():
        actual = _cell(header, col)  # already stripped
        ok = actual == expected if mode == "equals" else expected in actual
        if not ok:
            mismatches.append(
                f"col {col}: expected {mode} {expected!r}, got {actual!r}"
            )

    if mismatches:
        raise SheetStructureError(
            "gviz member-tab header did not match the expected member table. "
            "The requested tab may not exist (gviz silently serves a different "
            "tab in that case), gviz may have served a different tab, or the "
            "sheet structure changed. Mismatches:\n  - "
            + "\n  - ".join(mismatches)
            + "\nInspect the tab name and update config.GVIZ_SENTINEL_HEADERS "
            "/ column offsets before this scraper can run again."
        )


def parse_gviz(csv_text: str) -> list[MemberRow]:
    """Parse gviz CSV text into a list of ``MemberRow``.

    The header is line 1; member data begins on line 2. Each row is sliced to
    columns 0..``GVIZ_LAST_COL`` to drop trailing summary junk, then read until
    the first empty Member cell.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise SheetStructureError("gviz CSV was empty; cannot locate header row.")

    _validate_gviz_header(rows[0])

    members: list[MemberRow] = []
    for raw in rows[1:]:
        row = raw[: config.GVIZ_LAST_COL + 1]  # drop trailing summary columns
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


def scrape_member_tab(tab_name: str) -> GuildData:
    """Fetch, guard, parse, and wrap a named member tab.

    Raises:
        SheetStructureError: if the fetched tab is not a member table (wrong
            tab served, tab missing, or layout changed).
        RuntimeError: on fetch/HTTP failure.
    """
    csv_text = fetch_tab_csv(tab_name)
    members = parse_gviz(csv_text)  # wrong-tab guard runs inside
    return GuildData(
        tab=tab_name,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        member_count=len(members),
        members=members,
    )
