"""Character identity: the game's immutable numeric ``characterId``.

Display names change in-game; the id never does. This module owns every id rule
the build uses, so the rest of the code never re-derives one:

- ``parse_id``          the cross-repo contract's id rule (positive int, or a
                        ``/^\\s*\\d+\\s*$/`` string; anything else is "no id")
- ``find_id_column``    locate a characterId column BY HEADER, never by position
- ``with_character_id`` JSON emission: ``characterId`` only when known
- ``Resolver``          name -> id and id -> live name, from the live roll, the
                        Name History tab and the roster tab
- ``canonicalise``      rewrite member-tab rows to the name the game's roll gives
                        them now, attaching their id (logs ``renamed OLD → NEW (id N)``)
- ``find_member``       id first, then exact name, then unambiguous normalised name
- the Name History reader (``fetch_name_history_csv`` / ``parse_name_history`` /
  ``load_name_history``)

Imports only ``config`` and ``reader`` — never trials/signup/build — so every
model module can import it without a cycle.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, replace
from typing import Iterable, Optional

from . import config
from .reader import MemberRow, SheetStructureError, _cell, norm_name
from .scraper import fetch_tab_csv

_ID_RE = re.compile(r"\s*\d+\s*")


def parse_id(value) -> Optional[int]:
    """Contract id rule: a positive int, or a ``/^\\s*\\d+\\s*$/`` string; else None.

    Booleans are refused explicitly (an OLD Code.gs coerced the sign-up id column
    to TRUE/FALSE, and ``True`` is an ``int`` in Python).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else None
    if isinstance(value, str) and _ID_RE.fullmatch(value):
        v = int(value)
        return v if v > 0 else None
    return None


def find_id_column(header: Iterable) -> Optional[int]:
    """Index of the first header cell naming a characterId column, else None."""
    for i, h in enumerate(header):
        if str(h).strip().lower() in config.CHARACTER_ID_HEADERS:
            return i
    return None


def with_character_id(d: dict) -> dict:
    """Pop the dataclass key ``character_id``; re-add it as ``characterId`` only
    when it parses (and never while ``config.ID_JOIN_ENABLED`` is off, the pre-id
    output). Mutates and returns ``d``."""
    cid = parse_id(d.pop("character_id", None))
    if cid is not None and config.ID_JOIN_ENABLED:
        d["characterId"] = cid
    return d


@dataclass(frozen=True)
class HistoryRow:
    """One row of a Name History tab: a name this id has carried."""

    character_id: int
    name: str
    guild_id: str = ""
    first_seen: str = ""
    last_seen: str = ""


def fetch_name_history_csv(tab_name: str) -> str:
    """Fetch a Name History tab's gviz CSV export as text, addressed by name.

    ``&headers=1`` forces exactly ONE label row: the tab is all TEXT, and gviz may
    otherwise guess 0 header rows for an all-text table. This is NOT the
    ``&headers=0`` override (config.GVIZ_NO_HEADER_COLLAPSE), which blanks numeric
    labels.

    Raises:
        RuntimeError: on 401/403 (sharing revoked) or other HTTP/network errors.
    """
    return fetch_tab_csv(tab_name, "&headers=1")


def parse_name_history(csv_text: str, tab: str = "") -> list[HistoryRow]:
    """Parse a Name History tab. ``""`` -> ``[]``; header-only -> ``[]``.

    Leading all-blank lines are skipped; the first non-blank line MUST equal
    ``config.NAME_HISTORY_HEADER`` cell for cell, because gviz serves the FIRST tab
    for an unknown name — otherwise :class:`SheetStructureError`. Data rows with an
    invalid id or a blank name are skipped.
    """
    rows = list(csv.reader(io.StringIO(csv_text or "")))
    while rows and not any(c.strip() for c in rows[0]):
        rows.pop(0)
    if not rows:
        return []
    header = tuple(_cell(rows[0], i) for i in range(len(config.NAME_HISTORY_HEADER)))
    if header != config.NAME_HISTORY_HEADER:
        raise SheetStructureError(
            f"the {tab or 'Name History'!r} tab's header did not match "
            f"{list(config.NAME_HISTORY_HEADER)}; got {rows[0][:6]!r}. THE TAB MAY NOT "
            f"EXIST — gviz silently serves a different tab in that case."
        )
    out: list[HistoryRow] = []
    for r in rows[1:]:
        cid = parse_id(_cell(r, 0))
        name = _cell(r, 1)
        if cid is None or name == "":
            continue
        out.append(HistoryRow(cid, name, _cell(r, 2), _cell(r, 3), _cell(r, 4)))
    return out


def load_name_history(tab_name: str) -> tuple[list[HistoryRow], str]:
    """``(rows, warning)``; never raises. Flag off -> ``([], "")`` with no fetch.
    Any SheetStructureError / RuntimeError / network error -> ``([], reason)``, and
    the build behaves exactly as it did before the tab existed."""
    if not config.NAME_HISTORY_SOURCE_ENABLED:
        return [], ""
    try:
        return parse_name_history(fetch_name_history_csv(tab_name), tab_name), ""
    except (SheetStructureError, RuntimeError) as exc:
        return [], f"{tab_name!r}: {exc}"


def _unambiguous(pairs) -> tuple[dict[str, int], dict[int, str]]:
    """(norm name -> id, id -> first name seen) over parseable pairs. A normalised
    name held by two DIFFERENT ids is ambiguous and left out of the name map —
    the same rule roster.join applies to names."""
    by_name: dict[str, int] = {}
    ambiguous: set[str] = set()
    by_id: dict[int, str] = {}
    for name, raw in pairs:
        cid = parse_id(raw)
        if cid is None or not str(name or "").strip():
            continue
        name = str(name).strip()
        k = norm_name(name)
        by_id.setdefault(cid, name)
        if k in ambiguous:
            continue
        if k in by_name and by_name[k] != cid:
            del by_name[k]
            ambiguous.add(k)
            continue
        by_name[k] = cid
    return by_name, by_id


class Resolver:
    """name -> id and id -> live name.

    Precedence for name -> id: the live roll (unambiguous) > the Name History tab
    (the id whose row has the latest Last Seen; '' sorts oldest; a tie goes to the
    higher id) > the roster tab (unambiguous). id -> current name comes from the
    ROLL ONLY: history supplies the names an id has been seen with, never its
    current one.
    """

    def __init__(self, roll=(), roster=(), history: Iterable[HistoryRow] = ()):
        roll = list(roll)
        self._roll, self._live = _unambiguous(roll)
        # Roll names with a blank id: a current member whose id the roll did not
        # carry must not borrow one from history/roster (that id may be another
        # member's old name). Ambiguous roll names keep their fallback.
        self._roll_blank = {
            norm_name(str(n)) for n, raw in roll
            if str(n or "").strip() and parse_id(raw) is None
        }
        self._roster, _ = _unambiguous(roster)
        self._hist: dict[str, tuple[str, int]] = {}
        for h in history:
            cid = parse_id(h.character_id)
            if cid is None or not h.name.strip():
                continue
            k = norm_name(h.name)
            cand = (h.last_seen or "", cid)
            if k not in self._hist or cand > self._hist[k]:
                self._hist[k] = cand

    def id_for(self, name: str) -> Optional[int]:
        k = norm_name(name or "")
        if k in self._roll:
            return self._roll[k]
        if k in self._roll_blank:
            return None
        if k in self._hist:
            return self._hist[k][1]
        return self._roster.get(k)

    def current_name(self, cid) -> Optional[str]:
        cid = parse_id(cid)
        return self._live.get(cid) if cid is not None else None


def canonicalise(
    members: list[MemberRow], resolver: Resolver
) -> tuple[list[MemberRow], dict[str, str], list[str]]:
    """Rewrite each member row to the name the live roll gives its id now.

    Returns ``(members', renames, notes)`` where ``renames`` maps OLD -> NEW and
    ``notes`` are the human log lines (``renamed OLD → NEW (id N)``). NEVER
    mutates its input — the register was built from these very objects — and
    uses ``dataclasses.replace`` on changed rows only, so an unchanged row is the
    same object. When the member tab already carries a row under the NEW name,
    the OLD row is dropped (and noted) rather than modelling one person twice;
    ``renames`` still maps OLD -> NEW so the officers' register row finds the seat.
    ``config.ID_JOIN_ENABLED = False`` makes it a no-op.
    """
    if not config.ID_JOIN_ENABLED:
        return list(members), {}, []
    # Resolve every row FIRST, so a collision is judged against the names rows will
    # carry AFTER canonicalisation — not their original spellings. A swap or a chain
    # (Bob -> Carol, then Alice takes "Bob") must not drop Alice because the tab
    # once had a "Bob" row that has itself been renamed away.
    resolved = []
    for m in members:
        own = parse_id(m.character_id)
        cid = own if own is not None else resolver.id_for(m.name)
        cur = resolver.current_name(cid) if cid is not None else None
        resolved.append((m, own, cid, cur))
    taken = {
        norm_name(m.name) for m, _, cid, cur in resolved
        if cid is None or cur is None or norm_name(cur) == norm_name(m.name)
    }
    claimed: set[str] = set()
    out: list[MemberRow] = []
    renames: dict[str, str] = {}
    notes: list[str] = []
    for m, own, cid, cur in resolved:
        if cid is None:
            out.append(m)
            continue
        if cur is None or norm_name(cur) == norm_name(m.name):
            out.append(m if own == cid else replace(m, character_id=str(cid)))
            continue
        k = norm_name(cur)
        if k in taken or k in claimed:
            # Still OLD -> NEW: the officers' register row under OLD finds NEW's seat.
            renames[m.name] = cur
            notes.append(
                f"renamed {m.name} → {cur} (id {cid}): the member tab also has a row "
                f"for {cur}, so the {m.name} row is not modelled"
            )
            continue
        out.append(replace(m, name=cur, character_id=str(cid)))
        renames[m.name] = cur
        claimed.add(k)
        notes.append(f"renamed {m.name} → {cur} (id {cid})")
    return out, renames, notes


def find_member(members, name: str, character_id=None):
    """Id first (``parse_id``), then exact name, then unambiguous ``norm_name``."""
    cid = parse_id(character_id)
    if cid is not None:
        for m in members:
            if parse_id(getattr(m, "character_id", None)) == cid:
                return m
    for m in members:
        if m.name == name:
            return m
    k = norm_name(name or "")
    hits = [m for m in members if norm_name(m.name) == k]
    return hits[0] if len(hits) == 1 else None
