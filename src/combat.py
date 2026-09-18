"""Fetch and parse one guild's published COMBAT TEAMS from its Combat Teams tab.

THE ONLY INPUT IN THIS PIPELINE WRITTEN BY THE COMBAT OPTIMISER rather than by the
game, by an officer, or by the in-game sync module. The optimiser lives in
``~/pie/SCLIRoster`` (a Node CLI) and its ``report --publish-combat`` POSTs its
recommended teams — one row per seated member — through the Apps Script endpoint in
``apps-script/`` to a per-guild MACHINE-OWNED tab of the same public sheet everything
else here is read from:

    Member | Trial Hrid | Team | Role | Slot | Guild Id | Generated At
                                            [| Loadout Id | Loadout]

The last two cells are OPTIONAL and were appended on 2026-09-15. A tab written by the
older writer is seven wide and still parses here, with every seat's ``loadout_id``
left ``""`` — this reader is tolerant BY CONSTRUCTION so that it could ship before
the writer, which is the only reason the cross-repo rollout is safe in either order.

``Loadout`` is THE FIRST CELL IN THIS PIPELINE ever to contain a comma or a double
quote: it holds canonical JSON, and JSON is commas and quotes almost exclusively.
gviz's CSV export handles that the way RFC 4180 says — the field is wrapped in double
quotes and every internal double quote is DOUBLED (``"`` -> ``""``) — and
``csv.reader`` undoes exactly that, which is why the parse below reads whole cells
rather than splitting on commas anywhere. Nothing in this module may ever split a row
by hand; a hand-rolled split would shear every loadout at its first comma and hand the
fragments to the wrong columns.

That tab is the whole bridge. This module reads it, cross-checks it against the
guild's OWN sign-up tab, and ``build._write_guild`` attaches the result to
``trials.json`` as a top-level ``combat`` key, for the in-game userscript that glows
a member's two assigned combat tiles in Guild ▸ Trials.

Read through the same credential-free ``config.GVIZ_URL`` as the member, roster and
Buildings tabs, so it inherits their two properties and one trap:

  1. One clean machine-written header row; data begins on line 2. Unlike the member
     tabs there is no merged junk and no trailing summary columns, so the header
     guard below matches by EQUALS on all SEVEN cells.
  2. **DO NOT** append ``config.GVIZ_NO_HEADER_COLLAPSE``. See that constant's note
     and ``buildings.py``'s: "&headers=0" blanks the label of every numeric column,
     and ``Guild Id`` is numeric here.
  3. CRITICAL GOTCHA, shared with ``scraper.py`` and ``buildings.py``: gviz does NOT
     error on an unknown or misspelled sheet name — it silently serves a DIFFERENT
     tab. Measured 2026-09-09 on three invented names: each returned ~3518 bytes of
     the officers' "Trial Assignments" prose, the spreadsheet's FIRST tab. So "the
     tab does not exist" arrives here as PLAUSIBLE-LOOKING CONTENT, never as an
     error and never as emptiness. The header guard is the only thing that can tell
     the difference, which makes it mandatory rather than defensive, and it is why
     ``config.COMBAT_SENTINEL_HEADERS`` is equals-throughout on every one of the
     seven cells rather than a sentinel on one.

THREE OUTCOMES, AND THEY ARE NOT TWO (the same shape as ``buildings.py:29-40``). The
tabs are created by hand and start empty — "empty is fine; the first optimiser
publish fills them" (apps-script/README.md) — so:

  * rows            -> observed, teams modelled, ``trials.json`` says
                       ``available: true`` and the userscript glows.
  * "" / "\\n" /     -> ``observed=False``. NOT an error. The tab exists and the
    header only        optimiser has not published to it yet; ``trials.json`` says
                       ``available: false`` with that in words, which is a STATEMENT
                       and not a failure.
  * anything else   -> ``SheetStructureError``, which ``build._fetch_combat``
                       degrades on (warn + ``available: false``) rather than failing
                       the deploy. SC is ``required=True``: on 2026-07-25 a required
                       parse failure stopped every page of BOTH guilds shipping
                       (config.py's incident note), and combat teams are a
                       second-order input that must never be able to do that.

THE CROSS-CHECK, and why it is a SET of bosses and never a date. The optimiser and
the game refresh on their own schedules, so the tab can hold last week's pair while
the sign-up tab holds this week's, or the reverse. Both are caught by comparing the
tab's two hrids against the last two cells of this guild's own sign-up tab header
(spreadsheet F–G — the same fixed geometry ``signup.py`` and ``draw.py`` read the
skilling block by), normalised to lowercase alphanumerics so ``"Swarm"`` from the
sign-up header and ``/guild_combat/swarm`` from the hrid meet. Nothing here compares
``Generated At`` with ``week_date`` or with the game's week: a date comparison would
need the two writers to agree on a clock, and they do not have to agree on anything
but the bosses. When the sets differ the block is withheld and BOTH sets are named,
because the message cannot know which side is the stale one.

No credentials, no Google writes: this reads the publicly-exported CSV only. It
reuses the coercion helpers and the structure-error type from ``reader``, and the
sign-up geometry constants from ``draw``, rather than duplicating either.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote

import requests

from . import config
from . import draw as draw_model
from .reader import SheetStructureError, _cell, _to_int

# Column indices, matching config.COMBAT_SENTINEL_HEADERS (which is the guard for
# exactly these positions, so the two are read together or not at all).
COL_NAME = 0
COL_HRID = 1
COL_TEAM = 2
COL_ROLE = 3
COL_SLOT = 4
COL_GUILD_ID = 5
COL_GENERATED_AT = 6
# Appended 2026-09-15 (the pair) and 2026-09-18 (the name), and all OPTIONAL: guarded
# by config.COMBAT_OPTIONAL_HEADERS only when the header is wider than seven, and only
# for the columns the header actually has. Indices 0-6 above are untouched by design,
# so any reader slicing [:7] — this one included, before that date — is unaffected.
COL_LOADOUT_ID = 7
COL_LOADOUT = 8
# Appended 2026-09-18. Same rules, one exception: it has no pairing invariant of its
# own — it is an independent label that is either there or "".
COL_LOADOUT_NAME = 9

# Every Trial Hrid must start with this. A structural guard a display name could not
# admit, and the reason §3.1 of the plan publishes the hrid rather than "Swarm": it is
# the game's own identifier, it is what the userscript's two WebSocket comparisons
# already carry, and a skilling hrid landing in this column is a broken write.
COMBAT_HRID_PREFIX = "/guild_combat/"

# The two combat columns of a sign-up tab are the two AFTER the fixed skilling block —
# spreadsheet F–G, 0-based 5..6 — the geometry signup.py and draw.py read against.
# Derived from draw's constants rather than written as 5, so a change to the skilling
# block moves this with it instead of silently pointing at a skill.
COMBAT_PAIR_COL_START = draw_model.SKILLING_COL_START + draw_model.EXPECTED_TRIALS
COMBAT_PAIR_COUNT = 2


@dataclass
class CombatSeat:
    """One seated member, as the optimiser assigned them.

    No ``character_id``, by construction on the writer's side: ``trials.json`` names
    members by name everywhere else and the userscript joins on a folded name, and
    the id is the one thing SCLIRoster promises never leaves its own tree.
    """

    name: str
    role: str
    slot: str
    # The id of the loadout the optimiser RECOMMENDS for this seat — a key into
    # GuildCombat.loadouts, never the loadout itself (the artefact is normalised; the
    # tab is not). "" when the tab is seven wide, or when the optimiser could not
    # build one for this member. A consumer resolves it or shows nothing; there is no
    # third outcome.
    loadout_id: str = ""
    # The template's CURATED label for that recommendation — "Fire DPS (Blazing)",
    # "Healer (Blooming)", "Cursed". Thirteen such strings exist and they live in
    # exactly one place, SCLIRoster's data/templates/*.json; none of them is derivable
    # by titlecasing `role`, which is why they travel rather than being reconstructed.
    #
    # "" when the tab is seven or nine wide, or when the writer carried none. A
    # missing name degrades to "" and is NEVER guessed at — not from `role`, not from
    # the loadout, not from anywhere. A seat with no loadout already publishes "" for
    # its pair; the name degrades exactly the same way.
    #
    # It hangs on the SEAT and not in GuildCombat.loadouts because two different
    # templates can produce an identical DTO — the id is a hash of content — and then
    # one id would carry two rightful names, which _parse_loadout would refuse as a
    # conflict. On the seat there is no conflict to resolve.
    loadout_name: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "slot": self.slot,
            "loadout_id": self.loadout_id,
            "loadout_name": self.loadout_name,
        }


@dataclass
class CombatTeam:
    """One party: a boss, a team label, and the seats in tab (slot) order."""

    hrid: str
    team: str
    roster: list[CombatSeat] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hrid": self.hrid,
            "team": self.team,
            "party_size": len(self.roster),
            "roster": [s.to_dict() for s in self.roster],
        }


@dataclass
class GuildCombat:
    """One guild's published combat teams, wrapped with their provenance."""

    tab: str
    guild_key: str
    # False when the tab exists but the optimiser has never published to it. Distinct
    # from "could not be read": the remedy differs (run the optimiser vs fix the tab),
    # and a page that conflates them tells an officer his data is broken when it is
    # merely absent.
    observed: bool
    # OLDEST stamp among the rows, matching buildings.GuildBuildings.captured_at and
    # roster.Provenance.captured_at. "" when unobserved. One publish stamps every row
    # identically, so this differs from the newest only if a write was interrupted.
    generated_at: str = ""
    # Teams in TAB ORDER: first-seen order of (Trial Hrid, Team) walking rows top to
    # bottom. The writer sorts by Team then Slot, so this is stable across publishes
    # of the same recommendation.
    teams: list[CombatTeam] = field(default_factory=list)
    # id -> the recommended loadout, deduped: many seats share one. Empty when the
    # tab is seven wide. The ids are the optimiser's own content hashes and are NOT
    # recomputed here — the canonicalisation rule lives in exactly one file
    # (SCLIRoster's optimizer/src/publish/loadout.js) and a second implementation of
    # it in another language is a second implementation to drift. This side VERIFIES
    # instead: two rows sharing an id with different JSON is a structure error.
    loadouts: dict[str, dict] = field(default_factory=dict)

    @property
    def hrids(self) -> set[str]:
        """The distinct bosses this tab assigns — the cross-check's left-hand side."""
        return {t.hrid for t in self.teams}

    def to_dict(self) -> dict:
        """A JSON-serializable copy, for the CI summary and any debugging reader.

        NOT the trials.json shape: that is build._combat_block, which wraps these
        teams with the availability verdict the userscript gates on.
        """
        return {
            "tab": self.tab,
            "guild_key": self.guild_key,
            "observed": self.observed,
            "generated_at": self.generated_at,
            "teams": [t.to_dict() for t in self.teams],
            "loadouts": self.loadouts,
        }


def norm_trial(text: str) -> str:
    """``'Swarm'`` -> ``'swarm'``; ``'/guild_combat/swarm'`` -> ``'swarm'``.

    Lowercase alphanumerics of the last path segment — where the label and the hrid
    meet. The sign-up tab's combat headers are written by the sibling userscript from
    ``prettify(hrid)`` (``mwi-guild-signup-sync.user.js:521``), so for every boss in
    the nine-name vocabulary the two forms fold to the same string. Deliberately NOT
    ``reader.norm_name``: that folds case and whitespace but keeps punctuation, and
    the whole job here is to survive the ``/guild_combat/`` prefix and an underscore.
    """
    return re.sub(r"[^a-z0-9]", "", text.rsplit("/", 1)[-1].lower())


def fetch_combat_csv(tab_name: str) -> str:
    """Fetch a Combat Teams tab's gviz CSV export as text, addressed by tab name.

    Deliberately the same shape as ``scraper.fetch_tab_csv`` and
    ``buildings.fetch_buildings_csv``, including the 401/403 message: there is one way
    this sheet becomes unreachable and one thing to say about it.

    Raises:
        RuntimeError: on 401/403 (sheet sharing likely revoked) or other
            HTTP/network errors, with a message pointing at the likely cause. This
            stays FATAL, exactly as it is for every other tab — the member tab on the
            same host would have failed first.
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


def _validate_combat_header(header: list[str], tab: str) -> None:
    """Guard against gviz silently serving the wrong tab, or a hand-edited one.

    Matches by EQUALS on all seven REQUIRED cells (see the module docstring: this tab
    is machine-written, so there is no merged junk to tolerate). A wrong-tab serve —
    the only way "the tab does not exist" can reach this module — fails on cell 0: the
    officers' first tab opens with a blank cell, not "Member".

    The OPTIONAL loadout cells are checked only when the header is WIDER than the
    required seven, and only once the required seven have all matched. Both halves of
    that are deliberate:

      * Width-gated, because a seven-wide tab written by the older optimiser is a
        supported, indefinitely-safe state (§0 of the plan, and the whole reason this
        reader could ship first). Requiring nine would turn a rollback of the writer
        into a broken build.
      * Only after the required seven pass, because a wrong-tab serve is nineteen
        columns of officers' prose: checking the optional cells against that would add
        more mismatches to a message that is already naming the real problem, and
        the message's job is to say "this is not the combat tab", once.

    Since 2026-09-18 the writer emits a TENTH cell, ``Loadout Name``, and this reader
    must accept seven, nine AND ten. Two guards do that between them, and BOTH are
    needed:

      * A column declared in ``COMBAT_OPTIONAL_HEADERS`` that the header does not
        reach is SKIPPED rather than failed. Without that, declaring col 9 would
        refuse the nine-wide tab that is live today — ``_cell`` returns "" for a
        column that is not there, and "" is not "Loadout Name". That would be a
        self-inflicted outage on the first repository in the ship order.
      * The width must be one of ``config.COMBAT_ACCEPTED_WIDTHS``. Skipping absent
        columns alone would silently accept an EIGHT-wide tab, which is not an old
        writer but a torn one: a ``Loadout Id`` with no JSON beside it, whose loadout
        would then be attributed from nothing. Seven never reaches this branch, and is
        named in that tuple as documentation rather than as a check.
    """
    mismatches = []
    for col, (mode, expected) in config.COMBAT_SENTINEL_HEADERS.items():
        actual = _cell(header, col)  # already stripped
        ok = actual == expected if mode == "equals" else expected in actual
        if not ok:
            mismatches.append(
                f"col {col}: expected {mode} {expected!r}, got {actual!r}"
            )

    if not mismatches and len(header) > len(config.COMBAT_SENTINEL_HEADERS):
        if len(header) not in config.COMBAT_ACCEPTED_WIDTHS:
            mismatches.append(
                f"header is {len(header)} cells wide; the writer emits one of "
                f"{config.COMBAT_ACCEPTED_WIDTHS}"
            )
        for col, (mode, expected) in config.COMBAT_OPTIONAL_HEADERS.items():
            if col >= len(header):
                continue  # a narrower SUPPORTED width, not a mismatch
            actual = _cell(header, col)
            ok = actual == expected if mode == "equals" else expected in actual
            if not ok:
                mismatches.append(
                    f"col {col}: expected {mode} {expected!r}, got {actual!r}"
                )

    if mismatches:
        raise SheetStructureError(
            f"the {tab!r} tab's header did not match the expected combat teams "
            f"table. THE TAB MAY NOT EXIST — gviz silently serves a different tab "
            f"in that case, so create it by that exact name if it is missing — or "
            f"the optimiser's header changed, or somebody typed in this "
            f"machine-owned tab. Mismatches:\n  - "
            + "\n  - ".join(mismatches)
            + f"\nCompare against apps-script/README.md's block contract and "
            f"SCLIRoster's optimizer/src/publish/combatTab.js HEADER, and update "
            f"config.COMBAT_SENTINEL_HEADERS before this reader can run again."
        )


def _check_guild_id(raw: str, guild_key: str, tab: str, row_no: int) -> None:
    """Refuse a tab holding another guild's teams.

    Every row carries the id of the guild it was assigned for, and the optimiser
    routes a guild to a tab through a hand-written "guild slug -> tab" map
    (``combatTab.js`` ``TAB_BY_GUILD``). So the wrong guild's teams landing on this
    tab is one typo away, would look entirely plausible on the page, and would glow
    the wrong tiles for every member of both guilds. Raising rather than falling back
    is the same call ``buildings._check_guild_id`` makes for the same reason.
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
            f"combat teams, which would glow the wrong tiles for every member while "
            f"looking entirely plausible. Check the optimiser's TAB_BY_GUILD map in "
            f"SCLIRoster's optimizer/src/publish/combatTab.js, and config.GUILD_IDS."
        )


def _parse_loadout(
    raw: list[str], loadouts: dict[str, dict], tab: str, row_no: int
) -> str:
    """Read one row's optional ``Loadout Id`` / ``Loadout`` pair; return the id.

    ``""`` — and no entry in ``loadouts`` — for a seven-wide row, and for a nine-wide
    row whose pair is blank (a seated member the optimiser could not build a loadout
    for; the seat still publishes, and the CLI names the shortfall on its own side).

    VERIFIES, never recomputes. The id is the optimiser's content hash over its own
    canonical JSON, and rehashing it here would be a second implementation of a
    canonicalisation rule that deliberately lives in exactly one file. What this side
    CAN check without owning the rule is consistency: one publish clears and rewrites
    the tab from A1, so two rows carrying the same id with different JSON cannot be a
    stale row — it is a torn write or a hand edit, and either way one of the two
    blobs would be attributed to members it was never recommended for.

    Raises:
        SheetStructureError: on malformed JSON, on a non-object blob, on an id with
            no JSON beside it (or the reverse), or on an id/JSON conflict.
    """
    if len(raw) <= COL_LOADOUT_ID:
        return ""

    loadout_id = _cell(raw, COL_LOADOUT_ID)
    blob = _cell(raw, COL_LOADOUT)

    if loadout_id == "" and blob == "":
        return ""

    if loadout_id == "" or blob == "":
        raise SheetStructureError(
            f"the {tab!r} tab has a half-filled loadout on row {row_no}: "
            f"Loadout Id {loadout_id!r}, Loadout {blob[:60]!r}. The writer emits both "
            f"cells or neither, so one without the other is a torn write or a hand "
            f"edit. Re-run the optimiser's `report --publish-combat` rather than "
            f"editing this machine-owned tab."
        )

    try:
        parsed = json.loads(blob)
    except ValueError as exc:
        raise SheetStructureError(
            f"the {tab!r} tab's Loadout on row {row_no} is not valid JSON ({exc}). "
            f"The cell holds canonical JSON, which contains commas and double quotes; "
            f"gviz quotes and doubles them per RFC 4180 and csv.reader undoes that, so "
            f"a malformed blob here means the writer wrote one — or the tab was hand "
            f"edited. Got: {blob[:120]!r}"
        ) from exc

    if not isinstance(parsed, dict):
        raise SheetStructureError(
            f"the {tab!r} tab's Loadout on row {row_no} parsed as "
            f"{type(parsed).__name__}, not an object. A loadout is "
            f"{{equipment, abilities}}; anything else would reach the userscript as a "
            f"shape it cannot read. Got: {blob[:120]!r}"
        )

    seen = loadouts.get(loadout_id)
    if seen is not None and seen != parsed:
        raise SheetStructureError(
            f"the {tab!r} tab carries Loadout Id {loadout_id!r} on row {row_no} with "
            f"DIFFERENT JSON from an earlier row that shares it. The id is derived "
            f"from the content, so two spellings of one id cannot both be right, and "
            f"publishing either would attribute a recommendation to members it was "
            f"never made for. Every publish clears and rewrites this tab from A1, so "
            f"this is a torn write or a hand edit; re-run `report --publish-combat`."
        )
    loadouts[loadout_id] = parsed
    return loadout_id


def parse_combat(csv_text: str, guild_key: str, tab: str = "") -> GuildCombat:
    """Parse a Combat Teams tab's gviz CSV into a :class:`GuildCombat`.

    An EMPTY or header-only tab returns ``observed=False`` and raises nothing: the
    tabs are created by hand and empty and the optimiser may not have published yet,
    so that is a normal state (see the module docstring). Any other deviation raises
    ``SheetStructureError``, and nothing else — every failure mode the sheet can
    serve arrives through that one class, which is what lets
    ``build._fetch_combat`` promise that combat data can never stop the deploy.
    """
    tab = tab or config.COMBAT_TABS.get(guild_key, "")
    unobserved = GuildCombat(tab=tab, guild_key=guild_key, observed=False)

    if csv_text.strip() == "":
        # No bytes: the tab exists and has never been published to. NOTE that this is
        # NOT how a MISSING tab arrives — gviz serves another tab's content for that,
        # which the header guard below rejects. Nothing here keys on a byte count.
        return unobserved

    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        return unobserved

    _validate_combat_header(rows[0], tab or repr(guild_key))

    data = [r for r in rows[1:] if any(cell.strip() for cell in r)]
    if not data:
        # Header written, no rows yet. Same answer as zero bytes, and reached if a
        # publish ever seeds the header separately from the first real write.
        return unobserved

    # (hrid, team) -> CombatTeam, in first-seen order — which is dict order, and is
    # why this is a dict rather than a list plus a search.
    teams: dict[tuple[str, str], CombatTeam] = {}
    stamps: list[str] = []
    # id -> loadout, built as the rows are walked. The tab is DENORMALISED (every row
    # carries the whole blob, so a row is auditable on its own); the artefact is
    # normalised, and this dict is where the two meet.
    loadouts: dict[str, dict] = {}

    for offset, raw in enumerate(data):
        # +2: line 1 is the header, and rows are counted as a human reads the tab.
        row_no = offset + 2
        name = _cell(raw, COL_NAME)
        hrid = _cell(raw, COL_HRID)
        team = _cell(raw, COL_TEAM)

        _check_guild_id(_cell(raw, COL_GUILD_ID), guild_key, tab, row_no)

        if name == "":
            # On a HAND-maintained tab a blank name marks the end of the table
            # (reader.parse, signup.parse_signup). This tab is machine-written and
            # clear-and-rewritten from A1 with no blank rows, so a blank name here is
            # a broken write or a hand edit, and guessing which row it belonged to
            # would glow somebody else's tile.
            raise SheetStructureError(
                f"the {tab!r} tab has a blank Member on row {row_no}. This tab is "
                f"machine-written with no blank rows (every publish clears and "
                f"rewrites it from A1), so a blank name is a broken write or a hand "
                f"edit rather than the end of the table. Re-run the optimiser's "
                f"`report --publish-combat` rather than editing this tab."
            )

        if not hrid.startswith(COMBAT_HRID_PREFIX):
            raise SheetStructureError(
                f"the {tab!r} tab carries Trial Hrid {hrid!r} on row {row_no}, which "
                f"is not a combat trial (every one starts "
                f"{COMBAT_HRID_PREFIX!r}). Either a skilling trial reached the combat "
                f"writer or somebody typed in this machine-owned tab; the userscript "
                f"would derive a tile key that matches no combat tile."
            )

        stamp = _cell(raw, COL_GENERATED_AT)
        if stamp:
            stamps.append(stamp)

        loadout_id = _parse_loadout(raw, loadouts, tab, row_no)
        # Deliberately NOT inside _parse_loadout: that function owns a pairing
        # invariant (id and blob together or neither, SheetStructureError on half a
        # pair) and the name has no such invariant — it is an independent label that
        # is either there or "". _cell is bounds-safe, so a seven- or nine-wide row
        # yields "" with no branch at all.
        loadout_name = _cell(raw, COL_LOADOUT_NAME)

        key = (hrid, team)
        if key not in teams:
            teams[key] = CombatTeam(hrid=hrid, team=team)
        teams[key].roster.append(
            CombatSeat(
                name=name,
                role=_cell(raw, COL_ROLE),
                slot=_cell(raw, COL_SLOT),
                loadout_id=loadout_id,
                loadout_name=loadout_name,
            )
        )

    return GuildCombat(
        tab=tab,
        guild_key=guild_key,
        observed=True,
        generated_at=min(stamps) if stamps else "",
        teams=list(teams.values()),
        loadouts=loadouts,
    )


def scrape_combat_tab(tab_name: str, guild_key: str) -> GuildCombat:
    """Fetch, guard, parse and wrap one guild's Combat Teams tab.

    Raises:
        SheetStructureError: if the fetched tab is not a combat teams table (wrong
            tab served, tab missing, the optimiser's header changed, a hand edit) or
            holds another guild's id or a non-combat hrid. ``build._fetch_combat``
            degrades on this rather than failing the deploy.
        RuntimeError: on fetch/HTTP failure, which stays fatal as it does elsewhere.
    """
    csv_text = fetch_combat_csv(tab_name)
    return parse_combat(csv_text, guild_key, tab=tab_name)


def signup_combat_pair(csv_text: str, tab_label: str) -> list[str]:
    """The two combat-boss LABELS a guild's own sign-up tab header declares.

    The cross-check's right-hand side, and the reason this lives here rather than in
    ``draw.py``: ``draw.trial_columns`` returns the four SKILLING trials and validates
    them against the skill vocabulary, which the bosses have no place in. This reads
    the two cells AFTER that block by the same fixed geometry — spreadsheet F–G — the
    way the optimiser reads them from the other side (``trialSignup.js:97``,
    ``cols.slice(-2)``).

    Raises:
        SheetStructureError: if the CSV is empty, column 0 is not the ``User``
            sentinel (gviz served a different tab, or the tab was repurposed), the
            header is too short to hold F–G, or either cell is blank. A blank there
            is a rebuilt tab, not an unnamed boss.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise SheetStructureError(
            f"{tab_label!r} CSV was empty; cannot read the combat pair from its "
            "header row."
        )

    header = rows[0]
    if draw_model.USER_SENTINEL not in _cell(header, 0):
        raise SheetStructureError(
            f"{tab_label!r} header did not match: expected column 0 to contain "
            f"{draw_model.USER_SENTINEL!r}, got {_cell(header, 0)!r}. The tab may "
            "not exist (gviz silently serves a different tab in that case) or the "
            f"layout changed. Inspect the {tab_label!r} tab before this can run "
            "again."
        )

    end = COMBAT_PAIR_COL_START + COMBAT_PAIR_COUNT  # first column past the pair
    if len(header) < end:
        raise SheetStructureError(
            f"{tab_label!r} has too few columns to hold the two combat bosses in "
            f"columns F–G (>= {end} columns), got {len(header)}: {header!r}. The tab "
            f"layout changed or gviz served a different tab. Inspect the "
            f"{tab_label!r} tab before rerunning."
        )

    labels = [
        _cell(header, idx) for idx in range(COMBAT_PAIR_COL_START, end)
    ]
    blanks = [
        COMBAT_PAIR_COL_START + i for i, lbl in enumerate(labels) if lbl == ""
    ]
    if blanks:
        raise SheetStructureError(
            f"{tab_label!r} has a blank combat-boss header in column(s) "
            f"{', '.join(str(c) for c in blanks)}: {header!r}. An unnamed column is "
            f"a rebuilt or repurposed tab, not an unnamed boss, so the cross-check "
            f"refuses it rather than comparing against an empty string."
        )
    return labels


def cross_check(observed: GuildCombat, pair_labels: list[str]) -> str:
    """Empty when the tab and the sign-up header name the same two bosses.

    Otherwise the reason, in the words trials.json publishes verbatim.

    The ONLY freshness test on the build side, and it is a SET comparison of bosses —
    never a date. See the module docstring: the optimiser and the game refresh on
    their own schedules and need agree on nothing but which bosses this week runs.
    Order is not information (the game orders those columns as it likes), and case and
    form are not either (``norm_trial``), so only the membership of the two sets can
    differ meaningfully.

    When they differ the message names BOTH sets and both possibilities without
    guessing which side is stale, because it cannot know: either the optimiser has
    not been run for this week, or the game has not yet refreshed this guild's
    sign-up tab. Whichever it is, it resolves itself when the lagging side catches
    up, exactly as the skilling withhold does.
    """
    tab_set = {norm_trial(h) for h in observed.hrids}
    signup_set = {norm_trial(lbl) for lbl in pair_labels}
    if tab_set == signup_set:
        return ""
    return (
        f"stale: the {observed.tab!r} tab lists "
        f"[{', '.join(sorted(tab_set))}], the sign-up tab lists "
        f"[{', '.join(sorted(signup_set))}]. Those are different weeks' bosses. "
        f"EITHER the optimiser has not published for this week's pair yet, OR the "
        f"game has not yet refreshed this guild's sign-up tab — this message does "
        f"not guess which, because the two writers refresh on their own schedules. "
        f"No combat teams are published until they agree; it resolves itself once "
        f"the lagging side catches up."
    )
