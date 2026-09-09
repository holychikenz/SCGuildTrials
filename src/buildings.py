"""Fetch and parse one guild's building & shrine levels from its Buildings tab.

THE FIRST SOURCE IN THIS PIPELINE THAT THE GAME ITSELF WRITES ABOUT THE GUILD
rather than about its members. The in-game Tampermonkey module reads
``guildBuildingLevelMap`` off ``guild_updated`` / ``init_character_data`` and POSTs
it through the Apps Script endpoint in ``apps-script/`` to a per-guild tab of the
same public sheet everything else here is read from — 23 buildings and 5 shrines,
one row each:

    Building | Hrid | Kind | Level | Guild Id | Captured At

Before this module the ten skilling buildings' levels were typed into
``config.GUILD_BUILDING_LEVELS`` by hand, one map shared by both guilds, and that
map's own comment said to split it per guild "the moment real levels arrive".

Read through the same credential-free ``config.GVIZ_URL`` as the member and roster
tabs, so it inherits their two properties and one trap:

  1. One clean machine-written header row; data begins on line 2. Unlike the member
     tabs there is no merged junk and no trailing summary columns, so the header
     guard below matches by EQUALS throughout.
  2. **DO NOT** append ``config.GVIZ_NO_HEADER_COLLAPSE``. See that constant's note:
     "&headers=0" blanks the label of every numeric column, which is most of this tab.
  3. CRITICAL GOTCHA, shared with ``scraper.py``: gviz does NOT error on an unknown
     or misspelled sheet name — it silently serves a DIFFERENT tab. Measured
     2026-09-09: a bogus name returned 3518 bytes of the first tab's content. The
     header guard is therefore mandatory, not defensive.

THREE OUTCOMES, AND THEY ARE NOT TWO. The tabs are created by hand and start empty
(apps-script/README.md: "Add these two as **empty** tabs; the first write fills
them"), so:

  * 28 rows           -> observed, levels modelled.
  * 0 bytes / header   -> ``observed=False``. NOT an error. The guild runs on
    only                  ``config.GUILD_BUILDING_LEVELS``, and the page says the tab
                          has never been written rather than claiming a measurement
                          of zero. This is LI's position as of 2026-09-09.
  * anything else      -> ``SheetStructureError``, which ``build._fetch_guild``
                          degrades on (warn + fall back) rather than failing the
                          deploy, exactly as it does for the roster tab.

No credentials, no Google writes: this reads the publicly-exported CSV only. It
reuses the coercion helpers and the structure-error type from ``reader`` rather than
duplicating them.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from urllib.parse import quote

import requests

from . import config
from .reader import SheetStructureError, _cell, _to_int

# Column indices, matching config.BUILDINGS_SENTINEL_HEADERS (which is the guard for
# exactly these positions, so the two are read together or not at all).
COL_NAME = 0
COL_HRID = 1
COL_KIND = 2
COL_LEVEL = 3
COL_GUILD_ID = 4
COL_CAPTURED_AT = 5

KIND_BUILDING = "building"
KIND_SHRINE = "shrine"

SHRINE_HRID_PREFIX = "/guild_shrines/"


@dataclass
class GuildBuildings:
    """One guild's building & shrine levels, wrapped with its provenance.

    ``skill_levels`` is the only field the rate model consumes: it is keyed by TRIAL
    SKILL NAME so it can be bound straight over ``config.GUILD_BUILDING_LEVELS`` by
    ``trials.guild_building_levels_scope``. Everything else is carried so that "we
    read it and did not model it" is on the record rather than inferred from absence.
    """

    tab: str
    guild_key: str
    # False when the tab exists but has never been written. Distinct from an
    # observation of all-zeros, even though both currently model to the same numbers:
    # one is a measurement and the other is our ignorance, and a page that conflates
    # them tells an officer he has data he has not got.
    observed: bool
    # OLDEST capture among the rows, matching roster.Provenance.captured_at. "" when
    # unobserved. A single write stamps every row identically, so this differs from
    # the newest only if a write was interrupted part-way.
    captured_at: str = ""
    # TRIAL SKILL NAME -> building level, for the ten skilling buildings only.
    skill_levels: dict[str, int] = field(default_factory=dict)
    # Shrine short name ("force", "tempo", ...) -> level. THE GUILD'S TRUE CAP, and
    # the first direct measurement of it: config.GUILD_SHRINE_CAPS holds only a floor
    # inferred from the per-member maximum on the roster tab. Parsed and carried, but
    # deliberately NOT yet wired to that map — see the plan's §8.
    shrine_levels: dict[str, int] = field(default_factory=dict)
    # Every building hrid config.BUILDING_HRID_TO_SKILL does not name: the seven
    # combat buildings, the two encampments, the four utility buildings, and anything
    # the game adds later. Keyed by hrid, because these have no trial skill to key by.
    other_levels: dict[str, int] = field(default_factory=dict)
    # Rows whose Kind is neither "building" nor "shrine": recorded so a new Kind is
    # visible in one grep rather than silently absent from the model.
    ignored_hrids: list[str] = field(default_factory=list)

    @property
    def built_skills(self) -> dict[str, int]:
        """Only the skilling buildings actually built. The page's headline."""
        return {sk: lv for sk, lv in self.skill_levels.items() if lv}

    def to_dict(self) -> dict:
        """A JSON-serializable copy, for the provenance block and the CI summary."""
        return {
            "tab": self.tab,
            "guild_key": self.guild_key,
            "observed": self.observed,
            "captured_at": self.captured_at,
            "skill_levels": dict(self.skill_levels),
            "shrine_levels": dict(self.shrine_levels),
            "other_levels": dict(self.other_levels),
            "ignored_hrids": list(self.ignored_hrids),
        }


def fetch_buildings_csv(tab_name: str) -> str:
    """Fetch a Buildings tab's gviz CSV export as text, addressed by tab name.

    Deliberately the same shape as ``scraper.fetch_tab_csv``, including the 401/403
    message: there is one way this sheet becomes unreachable and one thing to say
    about it.

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


def _validate_buildings_header(header: list[str], tab: str) -> None:
    """Guard against gviz silently serving the wrong tab.

    Matches by EQUALS on all six cells (see the module docstring: this tab is
    machine-written, so there is no merged junk to tolerate). A wrong-tab serve fails
    on cell 0 — the member tab's first header cell is not "Building".
    """
    mismatches = []
    for col, (mode, expected) in config.BUILDINGS_SENTINEL_HEADERS.items():
        actual = _cell(header, col)  # already stripped
        ok = actual == expected if mode == "equals" else expected in actual
        if not ok:
            mismatches.append(
                f"col {col}: expected {mode} {expected!r}, got {actual!r}"
            )

    if mismatches:
        raise SheetStructureError(
            f"the {tab!r} tab's header did not match the expected building/shrine "
            f"levels table. The requested tab may not exist (gviz silently serves a "
            f"different tab in that case), or the Apps Script writer's header "
            f"changed. Mismatches:\n  - "
            + "\n  - ".join(mismatches)
            + f"\nCompare against apps-script/README.md's block contract and update "
            f"config.BUILDINGS_SENTINEL_HEADERS before this reader can run again."
        )


def _clamp_level(raw: str) -> int:
    """A level cell as a modelled level: 0..GUILD_BUILDING_MAX_LEVEL.

    Blank, negative and non-numeric all read as 0, and an inflated value is clamped
    down rather than trusted — the same contract ``trials.guild_building_skill_levels``
    applies to the config map, applied here so a malformed cell cannot reach the model
    even by a path that skips that function.
    """
    level = _to_int(raw) or 0
    return max(0, min(config.GUILD_BUILDING_MAX_LEVEL, level))


def _check_guild_id(raw: str, guild_key: str, tab: str, row_no: int) -> None:
    """Refuse a tab holding another guild's levels.

    Every row carries the id of the guild it was captured from, and the module routes
    a capture to a tab through a hand-edited "guild id -> tab" map. So the wrong
    guild's levels landing on this tab is one settings typo away, would look entirely
    plausible on the page, and would mis-plan a whole week. Raising rather than
    falling back is the same call ``config.shrine_caps`` makes for the same reason.
    """
    expected = config.GUILD_IDS.get(guild_key)
    if expected is None or raw == "":
        # No id configured for this guild, or an unstamped row: nothing to check
        # against. Not invented — a guard with no reference is no guard.
        return
    if _to_int(raw) != expected:
        raise SheetStructureError(
            f"the {tab!r} tab carries guild id {raw!r} on row {row_no}, but "
            f"{guild_key!r} is guild id {expected}. This tab holds ANOTHER GUILD'S "
            f"building levels, which would mis-plan the whole week while looking "
            f"entirely plausible on the page. Check the in-game module's "
            f"'Guild id -> Buildings tab' map, and config.GUILD_IDS."
        )


def parse_buildings(
    csv_text: str, guild_key: str, tab: str = ""
) -> GuildBuildings:
    """Parse a Buildings tab's gviz CSV into a :class:`GuildBuildings`.

    An EMPTY or header-only tab returns ``observed=False`` and raises nothing: the
    tabs are created by hand and empty, so that is a normal state (see the module
    docstring). Any other deviation raises ``SheetStructureError``.
    """
    tab = tab or config.BUILDING_TABS.get(guild_key, "")
    unobserved = GuildBuildings(tab=tab, guild_key=guild_key, observed=False)

    if csv_text.strip() == "":
        # Zero bytes: the tab exists and has never been written. gviz returns this
        # for an empty tab and returns another tab's CONTENT for a missing one, so
        # emptiness here is genuinely emptiness and not a missing tab.
        return unobserved

    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        return unobserved

    _validate_buildings_header(rows[0], tab or repr(guild_key))

    data = [r for r in rows[1:] if any(cell.strip() for cell in r)]
    if not data:
        # Header written, no rows yet. Same answer as zero bytes, and reached if the
        # writer ever seeds the header separately from the first real write.
        return unobserved

    skill_levels: dict[str, int] = {}
    shrine_levels: dict[str, int] = {}
    other_levels: dict[str, int] = {}
    ignored: list[str] = []
    captures: list[str] = []

    for offset, raw in enumerate(data):
        # +2: line 1 is the header, and rows are counted as a human reads the tab.
        row_no = offset + 2
        hrid = _cell(raw, COL_HRID)
        kind = _cell(raw, COL_KIND).lower()
        level = _clamp_level(_cell(raw, COL_LEVEL))

        _check_guild_id(_cell(raw, COL_GUILD_ID), guild_key, tab, row_no)

        captured = _cell(raw, COL_CAPTURED_AT)
        if captured:
            captures.append(captured)

        if kind == KIND_BUILDING:
            skill = config.BUILDING_HRID_TO_SKILL.get(hrid)
            if skill is not None:
                skill_levels[skill] = level
            else:
                # A combat/utility building, an encampment, or an hrid the game added
                # after this map was written. Kept, not dropped.
                other_levels[hrid] = level
        elif kind == KIND_SHRINE:
            shrine_levels[hrid.removeprefix(SHRINE_HRID_PREFIX)] = level
        else:
            ignored.append(hrid or _cell(raw, COL_NAME))

    return GuildBuildings(
        tab=tab,
        guild_key=guild_key,
        observed=True,
        captured_at=min(captures) if captures else "",
        skill_levels=skill_levels,
        shrine_levels=shrine_levels,
        other_levels=other_levels,
        ignored_hrids=ignored,
    )


def scrape_buildings_tab(tab_name: str, guild_key: str) -> GuildBuildings:
    """Fetch, guard, parse and wrap one guild's Buildings tab.

    Raises:
        SheetStructureError: if the fetched tab is not a building/shrine levels
            table (wrong tab served, tab missing, writer's header changed) or holds
            another guild's id. ``build._fetch_guild`` degrades on this rather than
            failing the deploy.
        RuntimeError: on fetch/HTTP failure, which stays fatal as it does elsewhere.
    """
    csv_text = fetch_buildings_csv(tab_name)
    return parse_buildings(csv_text, guild_key, tab=tab_name)
