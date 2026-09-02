"""Fetch and parse the guild skill-register CSV.

No credentials, no Google writes: this reads the publicly-exported CSV only.
"""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass, field
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
    house: Optional[int] = None  # per-skill house level (sheet "H" column); None if blank
    # --- Roster-sourced; None means "the roster did not say" -----------------
    # Written only by roster.merge, into the COPY it returns. ``tool`` above is
    # the manual tab's boolean ("has a Celestial tool"); these two carry what the
    # scripted roster tab actually observed, which the checkbox cannot express:
    # the item's name (so a Rainbow Chisel is not scored as a Holy one) and its
    # enhancement level (which the model otherwise assumes is +7 for everybody).
    # Both default to None so every existing constructor call is untouched, and
    # scraper.GuildData.to_dict omits them while they are unset so data.json stays
    # byte-identical with config.ROSTER_SOURCE_ENABLED off.
    tool_item: Optional[str] = None      # e.g. "Celestial Brush"
    tool_enhance: Optional[int] = None   # observed enhancement level, 0..20


@dataclass
class MemberRow:
    """A single guild member's parsed row."""

    name: str
    main_classes: str
    flex: str
    flex_levels: list[Optional[int]] = field(default_factory=list)
    skills: dict[str, SkillEntry] = field(default_factory=dict)
    # --- Roster-sourced; empty means "no roster row joined to this member" ---
    character_id: Optional[str] = None
    captured_at: Optional[str] = None
    # The member's OWN purchased skilling-shrine levels, by
    # config.GUILD_SHRINE_SKILLING_BUFFS key. LEVELS, not resolved bonuses, so
    # SHRINE_BUFFS_APPLY_IN_TRIALS and the channel table are still read at CALL
    # time — the property the whole rate model depends on. A shrine the roster
    # left blank is absent from the dict and falls back to the guild map.
    shrine_levels: dict[str, int] = field(default_factory=dict)
    # "<skill>.<field>" -> "roster" | "manual", plus "member" -> "roster" |
    # "manual" | "roster-only". Per FIELD, not per member: a gear-hider has real
    # levels, real houses and no tools, and the right answer is roster for what it
    # knows and manual for the rest.
    provenance: dict[str, str] = field(default_factory=dict)
    # --- Gear (src/gear.py); both written only by roster.merge / build ------
    # The parsed `gearSeen` union: {hrid: enhancement level or None}. THREE
    # states, and the difference between the last two is why this is Optional
    # rather than a plain dict (see gear.GearCell): None means the cell was BLANK
    # -- we did not look, or the member hides their gear -- while {} means we
    # LOOKED and they wore none of the tracked set. Nothing downstream treats the
    # two differently, by decision, but gear.GearAudit counts them apart, which is
    # how an upstream breakage in the writer would be noticed at all.
    gear: Optional[dict[str, Optional[int]]] = None
    # The RESOLVED terms, {skill: (speed, efficiency, success, gathering)},
    # computed ONCE per member in the parent by gear.resolve. trials.member_bonuses
    # reads this dict instead of walking the item table -- see src/gear.py's header
    # for why resolving in the hot loop would be wrong three ways.
    gear_bonuses: dict[str, tuple[float, float, float, float]] = field(
        default_factory=dict
    )


# Roster-sourced keys, and the value that means "unset" for each. These are
# OMITTED from every JSON serialisation while unset — see member_to_dict.
_UNSET_MEMBER_KEYS = {
    "character_id": None,
    "captured_at": None,
    "shrine_levels": {},
    "provenance": {},
}
_UNSET_SKILL_KEYS = {"tool_item": None, "tool_enhance": None}

# --- Fields dropped from every serialisation, SET OR NOT --------------------
# Measured on the live SC roster: the raw gear union costs 57 KB and the resolved
# bonuses another 59 KB, against a 256 KB members payload — a 45% increase to
# `data.json`, which the browser fetches on every page load.
#
# `gear_bonuses` is DERIVED: ten skills x four floats per member, recomputable
# from `gear` and the catalogue in microseconds, and read by nothing outside the
# rate model. Publishing it would be publishing a cache.
#
# `gear` is the raw evidence and this repository does like to publish its
# evidence — but nothing on any page reads it yet, and the aggregate counts an
# officer actually needs are already in the provenance block (how many members
# were visible, how many slot resolutions were observed against imputed). So it
# waits for the per-member gear badge that will use it, at which point deleting
# its line here is the whole change. Shipping 57 KB now against a follow-up that
# might want it is not a trade this file makes.
_NEVER_SERIALISED = ("gear", "gear_bonuses")


def member_to_dict(member: MemberRow) -> dict:
    """``dataclasses.asdict(member)`` with every UNSET roster key dropped.

    Left alone, ``asdict`` would write ``"tool_item": null`` onto every skill of
    every member even with ``config.ROSTER_SOURCE_ENABLED`` off, which would make
    this repository's bit-for-bit rollback claim false — and this repo pins its
    rollback claims with tests rather than asserting them in prose. Pinned by
    ``tests/test_roster.py::test_data_json_is_byte_identical_with_roster_off``.

    The filter is per FIELD rather than all-or-nothing, so a roster-backed member
    whose row named no tool does not carry a null for it either.

    Shared by ``processor.process`` (which writes ``_site/data.json``) and
    ``scraper.GuildData.to_dict``, for the same reason ``norm_name`` is shared:
    two copies of a rule about JSON shape will drift, and the drift shows up as a
    diff nobody expected.
    """
    d = asdict(member)
    for key in _NEVER_SERIALISED:
        d.pop(key, None)
    for key, unset in _UNSET_MEMBER_KEYS.items():
        if d.get(key) == unset:
            del d[key]
    for entry in d.get("skills", {}).values():
        for key, unset in _UNSET_SKILL_KEYS.items():
            if entry.get(key) == unset:
                del entry[key]
    return d


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


def norm_name(text: str) -> str:
    """Normalise a member name for JOINING two sheets that both name people.

    Collapses internal whitespace and casefolds — nothing more. It KEEPS digits
    and punctuation, so only case and spacing differences fold together and two
    genuinely distinct handles never collide.

    SHARED, and deliberately so. ``signup.py`` needs it to join the game-written
    sign-up tab to the hand-maintained member tab; ``roster.py`` needs it to join
    the script-written roster tab to the same member tab. Casing drifts on every
    one of those sheets (``dome``/``Dome``, ``VIadd``/``Viadd``, ``FeaI``/``Feai``)
    and an exact-only join silently loses six members per guild. Two normalisers
    that drift apart is exactly the bug this function exists to prevent, so there
    is one of it, here, rather than a copy in each caller.
    """
    return " ".join(text.split()).casefold()


def _to_bool(value: str) -> bool:
    """Literal 'TRUE' -> True, everything else (incl. blank/'FALSE') -> False."""
    return value.strip().upper() == "TRUE"


def _validate_header(rows: list[list[str]]) -> None:
    """Check the header against sentinel cells.

    Two rows are validated: the real header row (Member / Main Classes / Flex)
    and the skill-group-name row, whose block-start cells must spell each skill
    in ``config.SKILLS`` — this pins ``SKILL_BLOCK_START`` and
    ``SKILL_BLOCK_STRIDE`` for every block (see the SENTINEL_HEADERS note in
    config.py about the 2026-07-19 header reformat).
    """
    needed = max(config.HEADER_ROW_INDEX, config.SKILL_GROUP_ROW_INDEX)
    if len(rows) <= needed:
        raise SheetStructureError(
            "CSV has too few rows to contain the expected header rows "
            f"(need > {needed}, got {len(rows)})."
        )

    mismatches = []

    header = rows[config.HEADER_ROW_INDEX]
    for col, expected in config.SENTINEL_HEADERS.items():
        actual = _cell(header, col)
        if actual != expected:
            mismatches.append(
                f"header row col {col}: expected {expected!r}, got {actual!r}"
            )

    group = rows[config.SKILL_GROUP_ROW_INDEX]
    for i, skill in enumerate(config.SKILLS):
        col = config.SKILL_BLOCK_START + i * config.SKILL_BLOCK_STRIDE
        actual = _cell(group, col)
        if actual != skill:
            mismatches.append(
                f"skill-group row col {col}: expected {skill!r}, got {actual!r}"
            )

    if mismatches:
        raise SheetStructureError(
            "Guild sheet structure has changed; the column map in config.py "
            "no longer matches the sheet header. Mismatches:\n  - "
            + "\n  - ".join(mismatches)
            + "\nInspect the CSV and update config.SENTINEL_HEADERS / the skill "
            "block offsets before this pipeline can run again."
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
                house=_to_int(_cell(row, base + config.SKILL_HOUSE_OFFSET)),
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
