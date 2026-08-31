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

import copy
import csv
import io
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from . import config
from .reader import MemberRow, SheetStructureError, SkillEntry, norm_name
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


# ---------------------------------------------------------------------------
# The join: roster rows to the hand-maintained member tab
# ---------------------------------------------------------------------------
# Provenance tags. Per (member, skill, FIELD) — never per member, because a
# gear-hiding member has real levels, real houses, real shrines and no tools at
# all, and the right answer there is roster for what it knows and manual for the
# rest. Nine SC and seven LI members are exactly that case.
ROSTER = "roster"
MANUAL = "manual"
# A member who exists only on the roster and was seated from it alone.
ROSTER_ONLY = "roster-only"

_FIELDS = ("level", "house", "tool")


@dataclass
class JoinReport:
    """Who matched whom, and everything that did not match, for reporting.

    Both directions are carried, because both are actionable and neither may be
    swallowed: an unmatched MEMBER keeps their manual data (harmless, but worth
    knowing), while an unmatched ROSTER row is a real character the officers'
    tab has never heard of.
    """

    matched: dict[int, RosterRow] = field(default_factory=dict)
    normalized_matches: list[str] = field(default_factory=list)
    unmatched_members: list[str] = field(default_factory=list)
    unmatched_roster: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    # The unmatched roster ROWS, in tab order — the input to admission (§5.6).
    # Kept beside unmatched_roster (their names) rather than derived from it, so
    # the admission order is the tab's order and therefore deterministic.
    roster_only: list[RosterRow] = field(default_factory=list)

    def join_rate(self, member_count: int) -> float:
        """Fraction of the MANUAL tab's members that joined a roster row."""
        if member_count <= 0:
            return 0.0
        return len(self.matched) / member_count


def join(members: list[MemberRow], rows: list[RosterRow]) -> JoinReport:
    """Match member-tab rows to roster rows by name, case-insensitively.

    Exact name equality wins; otherwise the normalised key
    (:func:`reader.norm_name` — casefold plus collapsed whitespace) is tried.
    Measured, an exact-only join loses SIX members on each guild to nothing but
    capitalisation drift (``dome``/``Dome``, ``VIadd``/``Viadd``,
    ``FeaI``/``Feai``); case-insensitively SC joins 107/107 and LI 100/101.

    THE AMBIGUITY RULE IS ``signup.py``'s, verbatim: a normalised key held by two
    distinct rows on EITHER side matches nobody. Merging on an ambiguous key
    would give one person another person's levels, which is worse than leaving
    both on the manual tab, and the rule already exists here for the sign-up join
    for exactly that reason.
    """
    report = JoinReport()

    member_norm = [norm_name(m.name) for m in members]
    roster_norm = [norm_name(r.name) for r in rows]
    ambiguous_keys = {
        k for k, c in Counter(member_norm).items() if c > 1
    } | {k for k, c in Counter(roster_norm).items() if c > 1}

    roster_by_exact: dict[str, int] = {}
    for i, row in enumerate(rows):
        roster_by_exact.setdefault(row.name, i)
    roster_by_norm: dict[str, int] = {}
    for i, key in enumerate(roster_norm):
        if key not in ambiguous_keys:
            roster_by_norm.setdefault(key, i)

    used: set[int] = set()
    for idx, member in enumerate(members):
        j = roster_by_exact.get(member.name)
        if j is None:
            key = member_norm[idx]
            if key in ambiguous_keys:
                report.ambiguous.append(member.name)
                report.unmatched_members.append(member.name)
                continue
            j = roster_by_norm.get(key)
            if j is not None:
                report.normalized_matches.append(f"{rows[j].name} ≈ {member.name}")
        if j is None:
            report.unmatched_members.append(member.name)
            continue
        report.matched[idx] = rows[j]
        used.add(j)

    for i, row in enumerate(rows):
        if i not in used:
            report.unmatched_roster.append(row.name)
            report.roster_only.append(row)

    return report


# ---------------------------------------------------------------------------
# The merge: roster facts written into a COPY of the member rows
# ---------------------------------------------------------------------------
@dataclass
class Provenance:
    """Per-guild counters, for the build log, the pages and the JSON.

    Everything here is a count or a list of names — never a rate or a bonus.
    The point of it is that a member whose numbers come from the roster, from the
    manual tab, or from a constant is three different epistemic states, and the
    page has to be able to say which.
    """

    guild_key: str = ""
    member_count: int = 0          # members in the MERGED list
    roster_backed: int = 0         # manual members that joined a roster row
    manual_backed: int = 0         # manual members that did not
    admitted: int = 0              # roster-only members SEATED (§5.6)
    admitted_names: list[str] = field(default_factory=list)
    reported_not_seated: list[str] = field(default_factory=list)
    gear_hidden: list[str] = field(default_factory=list)
    captured_at: str = ""          # OLDEST capture among the joined rows
    # field -> tag -> count, over every (member, skill) the merge resolved.
    fields: dict[str, dict[str, int]] = field(default_factory=dict)
    normalized_matches: list[str] = field(default_factory=list)
    unmatched_members: list[str] = field(default_factory=list)
    unmatched_roster: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    # Non-empty when the roster was REFUSED for this guild: the reason, for the
    # warning and the on-page banner. The merge then returns the members
    # untouched, which is today's shipped behaviour rather than nothing.
    refused: str = ""
    # trials.ToolAudit, attached by build after the merge. Not filled here:
    # which items exist and which channel each feeds is MODEL knowledge, and this
    # module is a parser. Typed loosely so roster.py need not import trials.
    tools: object = None

    def to_dict(self) -> dict:
        return {
            "guild": self.guild_key,
            "member_count": self.member_count,
            "roster_backed": self.roster_backed,
            "manual_backed": self.manual_backed,
            "admitted": self.admitted,
            "admitted_names": list(self.admitted_names),
            "reported_not_seated": list(self.reported_not_seated),
            "gear_hidden": list(self.gear_hidden),
            "captured_at": self.captured_at,
            "fields": {k: dict(v) for k, v in self.fields.items()},
            "normalized_matches": list(self.normalized_matches),
            "unmatched_members": list(self.unmatched_members),
            "unmatched_roster": list(self.unmatched_roster),
            "ambiguous": list(self.ambiguous),
            "refused": self.refused,
            "tools": self.tools.to_dict() if self.tools is not None else None,
        }


def _tag(prov: Provenance, field_name: str, tag: str) -> None:
    prov.fields.setdefault(field_name, {})
    prov.fields[field_name][tag] = prov.fields[field_name].get(tag, 0) + 1


def _merged_entry(
    entry: Optional[SkillEntry],
    row: Optional[RosterRow],
    skill: str,
    member_provenance: dict[str, str],
    prov: Provenance,
) -> SkillEntry:
    """Resolve one member's one skill, FIELD BY FIELD.

    ``entry`` is the manual tab's cell (None for an admitted member, who has no
    manual row at all); ``row`` is the joined roster row (None for a member the
    roster has never seen). Each field independently takes the roster's value
    when the roster HAS one and its switch is on, and the manual value otherwise.
    ``top`` and ``bot`` are always the manual tab's: the roster does not carry
    body or legs, because the upstream module excludes them as rotating combat
    slots, and it never will.
    """
    manual_level = entry.level if entry else None
    manual_house = entry.house if entry else None
    # An admitted member has no checkbox to read. False (i.e. Holy) is the
    # conservative reading and it is only ever consulted when the roster ALSO
    # named no tool — from R3 the roster's item is what prices the tool.
    tool_check = entry.tool if entry else False
    # NECESSARILY False for an admitted member: there is no manual row carrying
    # the skilling top/bottom checkboxes and the roster does not carry those
    # slots. This UNDERSTATES an admitted member by up to two
    # ARMOUR_EFFICIENCY_PLUS7 terms. That is the right direction — a newcomer is
    # seated on the evidence we have, not on the evidence we wish we had — but it
    # is a real pessimism and it is counted in provenance rather than inferred.
    top = entry.top if entry else False
    bot = entry.bot if entry else False

    level, house = manual_level, manual_house
    tool_item: Optional[str] = None
    tool_enhance: Optional[int] = None
    tags = {"level": MANUAL, "house": MANUAL, "tool": MANUAL}

    if row is not None:
        if config.ROSTER_USE_LEVELS and row.levels.get(skill) is not None:
            level = row.levels[skill]
            tags["level"] = ROSTER
        if config.ROSTER_USE_HOUSES and row.houses.get(skill) is not None:
            house = row.houses[skill]
            tags["house"] = ROSTER
        if config.ROSTER_USE_TOOLS and row.tools.get(skill) is not None:
            tool_item = row.tools[skill]
            tool_enhance = row.tool_enh.get(skill)
            tags["tool"] = ROSTER

    for name in _FIELDS:
        member_provenance[f"{skill}.{name}"] = tags[name]
        _tag(prov, name, tags[name])

    return SkillEntry(
        level=level,
        tool=tool_check,
        top=top,
        bot=bot,
        house=house,
        tool_item=tool_item,
        tool_enhance=tool_enhance,
    )


def _admitted_member(row: RosterRow, prov: Provenance) -> MemberRow:
    """Build a MemberRow for a character who exists only on the roster (§5.6).

    ``main_classes`` / ``flex`` / ``flex_levels`` are left empty: the model never
    reads them (no reference in trials.py or optimizer.py — they are register
    decoration). ``top`` and ``bot`` are False for every skill, necessarily; see
    :func:`_merged_entry`.
    """
    member_provenance: dict[str, str] = {"member": ROSTER_ONLY}
    skills = {
        skill: _merged_entry(None, row, skill, member_provenance, prov)
        for skill in config.SKILLS
    }
    return MemberRow(
        name=row.name,
        main_classes="",
        flex="",
        flex_levels=[],
        skills=skills,
        character_id=row.character_id or None,
        captured_at=row.captured_at or None,
        shrine_levels=_shrine_levels(row),
        provenance=member_provenance,
    )


def _shrine_levels(row: RosterRow) -> dict[str, int]:
    """The member's OWN purchased skilling-shrine levels, blanks omitted.

    Levels, not resolved bonuses, so ``SHRINE_BUFFS_APPLY_IN_TRIALS`` and the
    channel table in ``config.GUILD_SHRINE_SKILLING_BUFFS`` are still read at
    CALL time — the property the whole rate model depends on. A shrine the roster
    left blank is absent, and falls back to the guild map downstream.
    """
    if not config.ROSTER_USE_SHRINES:
        return {}
    return {k: v for k, v in row.shrines.items() if v is not None}


def merge(
    members: list[MemberRow],
    report: JoinReport,
    guild_key: str = "",
) -> tuple[list[MemberRow], Provenance]:
    """Return a NEW member list carrying the roster's facts, plus provenance.

    A DEEP COPY: ``members`` is never mutated. ``index.html`` is built from the
    unmerged rows and must keep mirroring the officers' own tab exactly, stale
    cells included — that is the page an officer uses to notice a stale cell, and
    conflating it with the model would destroy the one page that reports data
    quality.

    Levels and houses need no consumer change at all: they are written into the
    ``SkillEntry.level`` / ``.house`` fields that ``_resolve_level_and_checks``
    already reads, so ``member_bonuses``, ``_prepare_member``, ``simulate_race``,
    the optimizer, ``signup.py`` and ``calibrate.py`` are untouched and simply
    read better numbers out of the fields they already read.

    Roster-only characters are APPENDED, after the manual members, in roster-tab
    order — deterministic, so the seed-fixed optimizer trajectory is
    reproducible (§5.6).

    THE JOIN-RATE REFUSAL. Below ``config.ROSTER_MIN_JOIN_RATE`` the roster is
    refused for this guild and the members come back untouched. It guards the
    catastrophic case rather than the common one: one lost member is harmless
    (they keep today's behaviour), but gviz serving a different tab past the
    header guard would silently reprice a whole guild.
    """
    prov = Provenance(
        guild_key=guild_key,
        normalized_matches=list(report.normalized_matches),
        unmatched_members=list(report.unmatched_members),
        unmatched_roster=list(report.unmatched_roster),
        ambiguous=list(report.ambiguous),
    )

    rate = report.join_rate(len(members))
    if members and rate < config.ROSTER_MIN_JOIN_RATE:
        prov.refused = (
            f"only {len(report.matched)} of {len(members)} members "
            f"({rate:.0%}) joined a roster row, below the "
            f"{config.ROSTER_MIN_JOIN_RATE:.0%} floor. The roster is REFUSED for "
            f"this guild and every member keeps the manual tab's data — which is "
            f"today's shipped behaviour, not a degraded one. A join rate this low "
            f"usually means gviz served a different tab, or the roster tab was "
            f"rebuilt for a different guild."
        )
        prov.member_count = len(members)
        prov.manual_backed = len(members)
        prov.reported_not_seated = list(report.unmatched_roster)
        return [copy.deepcopy(m) for m in members], prov

    merged: list[MemberRow] = []
    captures: list[str] = []
    for idx, member in enumerate(members):
        row = report.matched.get(idx)
        member_provenance: dict[str, str] = {"member": ROSTER if row else MANUAL}
        skills = {
            skill: _merged_entry(
                member.skills.get(skill), row, skill, member_provenance, prov
            )
            for skill in config.SKILLS
        }
        # Any skill the manual tab carries that config.SKILLS does not is copied
        # through untouched rather than dropped — the merge may not lose data.
        for skill, entry in member.skills.items():
            if skill not in skills:
                skills[skill] = copy.deepcopy(entry)

        if row is not None:
            prov.roster_backed += 1
            if row.captured_at:
                captures.append(row.captured_at)
            if all(v is None for v in row.tools.values()):
                prov.gear_hidden.append(member.name)
        else:
            prov.manual_backed += 1

        merged.append(
            MemberRow(
                name=member.name,
                main_classes=member.main_classes,
                flex=member.flex,
                flex_levels=list(member.flex_levels),
                skills=skills,
                character_id=(row.character_id or None) if row else None,
                captured_at=(row.captured_at or None) if row else None,
                shrine_levels=_shrine_levels(row) if row else {},
                provenance=member_provenance,
            )
        )

    if config.ROSTER_ADMITS_NEW_MEMBERS:
        for row in report.roster_only:
            merged.append(_admitted_member(row, prov))
            prov.admitted += 1
            prov.admitted_names.append(row.name)
            if row.captured_at:
                captures.append(row.captured_at)
            if all(v is None for v in row.tools.values()):
                prov.gear_hidden.append(row.name)
    else:
        prov.reported_not_seated = list(report.unmatched_roster)

    prov.member_count = len(merged)
    prov.captured_at = min(captures) if captures else ""
    return merged, prov
