"""Sign-up-aware trial planning.

Each guild's sign-up sheet tab ("SC Trial Signup" for Survey Corps, "LI Trial
Signup" for Lactose lntolerance — see :data:`SIGNUP_TABS`) records who has
*volunteered* for which of this week's four skilling trials. This module turns
those real sign-ups into a plan the guild can actually run:

  1. **Enforce** the sign-ups — every volunteer is LOCKED into the exact trial
     they ticked; they are never moved or benched.
  2. **Recommend fills** — the still-open seats are offered to members who
     signed up for *nothing* (the uncommitted pool), choosing the placement that
     most raises total guild points and never seating anyone who would lower a
     party's tier (the same no-regret rule as :func:`src.optimizer._fill_bench`).
  3. **Compare to optimal** — the enforced plan is diffed against the
     unconstrained full-roster optimum (the very assignment ``trials.html``
     already computes), yielding the score gap and the advisory list of swaps
     (recruit / bench / move) that would close it.

PURE-ish LOGIC: :func:`plan` and everything it calls are network-free and take
their inputs as plain data. Only :func:`fetch_signup_csv` touches the network
(the anonymous gviz CSV export, exactly like :mod:`src.scraper`). HTML lives in
``build.py``.

The SC Trial Signup tab layout (fixed skilling block since 2026-07-24)::

    col 0     (A)    = "User"  (member name)
    cols 1..4 (B–E)  = this week's FOUR skilling trials, one TRUE/FALSE tick-box
                       each — ALWAYS in these four fixed positions.
    cols 5..  (F..)  = the two combat trials (+ any stray columns) — IGNORED.

The companion Tampermonkey writer (``guild-signup-sync``) emits exactly this
compact layout — ``User | <4 skilling trials> | <2 combat trials>``, e.g.
``User | Woodcutting | Crafting | Alchemy | Milking | Hedgehog | Jellyfish``.

Only the four fixed skilling columns (B–E) are read; everything from column F on
is ignored *by position*, so a combat column can never be mistaken for a sign-up
(this replaced the earlier "scan every column / all-skills" parsing). The four
skilling columns are NOT laid out in the officers' Trial 1..4 draw order — the
game writes them in its own ``guildWeeklyTrialSet`` order — so each column's
SKILL is resolved from its HEADER (via :data:`_HEADER_TO_SKILL`,
case/punctuation-insensitive, with the trial-name aliases ``Alchemy`` →
``Bell Farming`` and ``Cheesesmithing`` → ``C.Smithing``), NOT inferred from its
position. A blind position→Trial-N map would scramble every sign-up whenever the
two orders differ (they currently do: col B is Woodcutting while draw Trial 1 is
Milking). Two guards fail loudly rather than emit garbage: the "User" sentinel in
col 0 (gviz silently serves a *different* tab on a bad name — see
:mod:`src.scraper`) and the requirement that each of columns B–E carry a
recognised skill header.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import requests

from . import config
from .reader import MemberRow, SheetStructureError, _cell, _to_bool
from .optimizer import AssignmentScorer
from .trials import (
    RosterEntry,
    rate,
    simulate_race,
    clear_probability,
    tier_clear_seconds,
    time_slack_fraction,
)


# ---------------------------------------------------------------------------
# Fetch + parse the "SC Trial Signup" tab
# ---------------------------------------------------------------------------
# SHEET CHANGE (2026-07): the sign-up tab was renamed from "Trial Signup" to
# "SC Trial Signup" when the guild split sign-ups per sub-guild (SC / LI), and a
# matching "LI Trial Signup" tab was added. The tick-box LAYOUT is identical for
# both (col 0 = User, then this week's four skilling trials in cols B–E). The
# build now runs the whole pipeline once per guild (see build.py GUILD_SITES),
# each guild reading its OWN sign-up tab against its OWN member tab. NOTE: gviz
# does NOT error on an unknown tab name — it silently serves a *different* tab —
# so a stale name here does not fail loudly at fetch; it is the "User" sentinel
# in parse_signup that catches it.
#
# ``SIGNUP_TABS`` mirrors ``config.TABS`` (the per-guild member tabs); the two
# keys must stay in lockstep so a guild's member tab and sign-up tab are paired.
SIGNUP_TABS = {
    "sc": "SC Trial Signup",
    "li": "LI Trial Signup",
}
# Backward-compatible default: the SC sign-up tab (the original single-guild tab).
SIGNUP_TAB = SIGNUP_TABS["sc"]


def fetch_signup_csv(tab_name: str = SIGNUP_TAB) -> str:
    """Fetch the sign-up tab's gviz CSV export as text, addressed by name.

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


def _norm_header(text: str) -> str:
    """Normalise a header cell for matching: lowercase, alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _norm_name(text: str) -> str:
    """Normalise a member / sign-up name for JOINING the two sheets.

    Collapses internal whitespace and casefolds — nothing more. The sign-up
    "User" cell is the raw in-game name, while the member tab is hand-maintained,
    so the two routinely differ only by capitalisation (e.g. sign-up ``Dome`` vs
    member ``dome``); an exact-only join silently dropped such sign-ups. Unlike
    :func:`_norm_header` this KEEPS digits and punctuation, so only case/spacing
    differences fold together and two genuinely distinct handles never collide.
    """
    return " ".join(text.split()).casefold()


# Normalised header token -> the ``config.SKILLS`` sheet-column name it denotes.
# Every skill matches its own name; plus the two trial-name aliases the game
# writer uses: "Alchemy" -> "Bell Farming" (the joke column) and "Cheesesmithing"
# -> "C.Smithing".
_HEADER_TO_SKILL: dict[str, str] = {
    _norm_header(sk): sk for sk in config.SKILLS
}
_HEADER_TO_SKILL[_norm_header("Alchemy")] = "Bell Farming"
_HEADER_TO_SKILL[_norm_header("Cheesesmithing")] = "C.Smithing"

# The four skilling-trial tick columns are ALWAYS spreadsheet columns B–E, i.e.
# 0-based indices SKILLING_COL_START .. SKILLING_COL_START + SKILLING_COL_COUNT-1.
# Everything from column F (index 5) on is combat/extra and ignored by position.
# SKILLING_COL_COUNT mirrors draw.EXPECTED_TRIALS (the guild draws exactly four
# skilling trials each cycle); kept as a local constant so signup.py need not
# import draw.
SKILLING_COL_START = 1
SKILLING_COL_COUNT = 4


def parse_signup(csv_text: str, tab_label: str = "sign-up") -> dict[str, set[str]]:
    """Parse the sign-up CSV into ``{member_name: {sheet_skill_names_ticked}}``.

    ``tab_label`` names the tab in any :class:`SheetStructureError` so a failure
    reads e.g. "SC Trial Signup tab ..." / "LI Trial Signup tab ..." — it has no
    effect on parsing (the layout is identical for every guild).

    Keys are member names in the "User" column; values are the set of
    ``config.SKILLS`` names the member ticked TRUE. Reads until the first blank
    User cell.

    Only the four FIXED skilling-trial columns — spreadsheet B–E (0-based indices
    ``SKILLING_COL_START`` .. ``SKILLING_COL_START + SKILLING_COL_COUNT - 1``) —
    are read; columns F onward (the two combat trials, blanks, stray helpers) are
    ignored *by position*. Each of the four columns is mapped to its sheet-skill
    name via its HEADER (:data:`_HEADER_TO_SKILL`), because the game writes the
    four skilling columns in its own order rather than the officers' Trial 1..4
    draw order — so a ticked column is resolved by *which skill that column is*,
    not by where the trial sits in the draw. The Alchemy trial resolves to the
    "Bell Farming" column, so the downstream planner (which maps trial skills onto
    sheet columns via ``config.TRIAL_SKILL_TO_SHEET_COLUMN``) is unchanged.

    Raises:
        SheetStructureError: if the CSV is empty, column 0 is not "User" (gviz
            silently serves a *different* tab on a bad name), there are fewer than
            ``SKILLING_COL_START + SKILLING_COL_COUNT`` columns, or any of the four
            skilling columns (B–E) carries a header that is not a recognised skill
            (a layout change or the wrong tab). Failing loudly beats silently
            mis-seating or dropping sign-ups; ``build.py`` catches it and emits an
            inactive placeholder page.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise SheetStructureError(
            f"{tab_label} tab CSV was empty; cannot locate the header row."
        )

    header = rows[0]
    if "User" not in _cell(header, 0):
        raise SheetStructureError(
            f"{tab_label} tab header did not match: expected column 0 to contain "
            f"'User', got {_cell(header, 0)!r}. The tab may not exist (gviz "
            "silently serves a different tab in that case) or the layout "
            f"changed. Inspect the {tab_label!r} tab before this can run again."
        )

    end = SKILLING_COL_START + SKILLING_COL_COUNT  # first column past the block
    if len(header) < end:
        raise SheetStructureError(
            f"{tab_label} tab has too few columns: expected 'User' plus the four "
            f"skilling trials in columns B–E (>= {end} columns), got "
            f"{len(header)}: {header!r}. The tab layout changed or gviz served a "
            f"different tab. Inspect the {tab_label!r} tab before rerunning."
        )

    # The four skilling columns are ALWAYS B–E; resolve each to its sheet-skill
    # via its header. Anything from column F on (combat trials, extras) is never
    # looked at. A non-skill header inside B–E is a structural error (loud).
    col_to_skill: dict[int, str] = {}
    for idx in range(SKILLING_COL_START, end):
        raw = _cell(header, idx)
        skill = _HEADER_TO_SKILL.get(_norm_header(raw))
        if skill is None:
            raise SheetStructureError(
                f"{tab_label} tab column {idx} (spreadsheet "
                f"{chr(ord('A') + idx)}) has header {raw!r}, which is not a known "
                "skilling trial; columns B–E must be this week's four skilling "
                f"trials. Known skills: {sorted(set(_HEADER_TO_SKILL.values()))}. "
                "The tab layout changed or gviz served a different tab."
            )
        col_to_skill[idx] = skill

    picks: dict[str, set[str]] = {}
    for row in rows[1:]:
        name = _cell(row, 0)
        if name == "":
            break  # first blank User cell ends the table
        picks[name] = {
            skill for idx, skill in col_to_skill.items() if _to_bool(_cell(row, idx))
        }
    return picks


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass
class SignupRosterEntry:
    """One member's line in an enforced-plan trial roster."""

    name: str
    level: Optional[int]
    tool: bool
    top: bool
    bot: bool
    rate_final: float
    status: str  # "assigned" (volunteer) | "recommended" (fill from free pool)
    fill_gain: Optional[int] = None  # points this fill added (recommended only)
    lifts_tier: bool = False  # True when the fill strictly raised the party's points


@dataclass
class SignupTrial:
    """One trial in the enforced plan: locked volunteers + recommended fills.

    ``clear_seconds`` / ``slack_fraction`` record HOW NARROWLY this lineup banked
    its score: the clock reading when the last completed tier finished, and the
    fraction of the 3600-second budget still unspent at that moment. Points alone
    cannot show this — they are a step function of the tier — so a trial holding a
    tier by nine seconds looks identical to one holding it by ten minutes. The
    optimizer's safety pass maximises this margin on the UNCONSTRAINED optimum
    (:func:`src.optimizer._refine_slack`); the enforced sign-up plan cannot, since
    the volunteers are locked, so here it is reported instead of optimised.
    """

    skill: str
    party_size: int
    tier_reached: int
    points: int
    open_seats: int  # seats still empty after fills (cap - party_size)
    roster: list[SignupRosterEntry] = field(default_factory=list)
    # Seconds elapsed when the last cleared tier finished; None if no tier held.
    clear_seconds: Optional[float] = None
    # Unspent share of the budget at that moment, in [0, 1); 0.0 when no tier held.
    slack_fraction: float = 0.0
    # The same fact as odds: P(this lineup actually banks the tier it is credited
    # with), conditional on the assigned party turning up. None when no tier held.
    # A margin is ordinal; officers plan against probabilities, and the mapping is
    # violently non-linear near the buzzer — see trials.clear_probability.
    clear_probability: Optional[float] = None


@dataclass
class Swap:
    """One advisory, strictly-improving move (or move-group) from the enforced plan.

    Each entry RAISES total guild points by ``gain > 0``. Two kinds occur:

    * a **single** move (``action`` in ``recruit`` / ``bench`` / ``move`` /
      ``swap``) that improves points on its own — the classic best-improvement
      hill-climb step; and
    * a **reshuffle** (``action == "reshuffle"``): a short *sequence* of
      individually break-even swaps into one under-tier trial that together cross
      its next tier threshold. It exists because points are a STEP function of
      tier — no single swap crosses the line, so a strict single-move climb stalls
      one tier below the optimum and (before this) recommended nothing. The
      component swaps are listed in ``moves``; ``gain`` is the whole group's net.

    The list is still the minimal set of strictly-improving moves — every entry
    raises the score — in contrast to a naive diff against the global optimum,
    which reshuffles the whole guild for no real gain.
    """

    member: str
    action: str  # "recruit" | "bench" | "move" | "swap" | "reshuffle"
    from_skill: Optional[str]
    to_skill: Optional[str]
    note: str
    partner: Optional[str] = None  # the other member, for an "action == swap"
    gain: int = 0  # guild points this move (or group) adds
    # For ``action == "reshuffle"``: the component swaps, each
    # ``{"in": name, "out": name, "from_skill": donor_trial}``. ``None`` otherwise.
    moves: Optional[list[dict]] = None


@dataclass
class SafetySwap:
    """One advisory, POINTS-PRESERVING move that widens the thinnest time margin.

    The counterpart to :class:`Swap`: where a ``Swap`` buys points, a ``SafetySwap``
    buys *room*. Every entry leaves the score exactly as it was and strictly lifts the
    thinnest trial — both enforced by construction, see :func:`_safety_swaps`.
    Uncommitted members are spent first; an entry that has to move a volunteer sets
    ``overrides_signup`` so the page can flag it rather than slip it past the reader.
    ``min_before`` / ``min_after`` are the thinnest margin across the banking trials
    before and after this move, and ``trial_changes`` names the trials whose margin
    actually moved.
    """

    member: str
    action: str  # "move" | "bench" | "seat" | "swap"
    from_skill: Optional[str]
    to_skill: Optional[str]
    note: str
    partner: Optional[str] = None  # the other member, for ``action == "swap"``
    min_before: float = 0.0
    min_after: float = 0.0
    # [{"skill": str, "before": float, "after": float}] for each trial that changed.
    trial_changes: list[dict] = field(default_factory=list)
    # True when the move relocates a VOLUNTEER out of the trial they ticked. The
    # search only resorts to these once the uncommitted members alone cannot lift the
    # thinnest trial to the target, and the page flags them distinctly: they are the
    # same kind of override the points swaps already make, but they must be a
    # deliberate choice rather than a surprise.
    overrides_signup: bool = False


@dataclass
class SignupPlan:
    """Everything the sign-up page needs for one week's real sign-ups."""

    generated_at: str
    week_date: str
    skills: list[str]
    cap: int
    target_scale: float
    roster_count: int
    signup_count: int
    non_signups: list[str]
    conflicts: list[str]
    enforced_total: int
    optimal_total: int
    gap: int
    reachable_total: int  # score after applying the listed swaps
    # Thinnest time margin across the trials that actually banked a tier (the
    # weakest link in the lineup's safety), or None when no trial banked one.
    # Trials that reached no tier are EXCLUDED rather than counted as 0.0, so
    # "scored nothing" is never mistaken for "held a tier by a hair".
    min_slack_fraction: Optional[float] = None
    # The per-trial clock these margins are measured against (3600s), carried so
    # signup.json is self-describing.
    budget_seconds: float = config.TRIAL_TIME_BUDGET_SECONDS
    # Thinnest margin once the advisory safety swaps below are applied (None when no
    # trial banks a tier). Equals ``min_slack_fraction`` when there is nothing to do.
    safety_min_slack: Optional[float] = None
    trials: list[SignupTrial] = field(default_factory=list)
    enforced_bench: list[str] = field(default_factory=list)
    optimal_summary: list[dict] = field(default_factory=list)
    swaps: list[Swap] = field(default_factory=list)
    # Advisory POINTS-PRESERVING moves that widen the thinnest margin, uncommitted
    # members first (see :func:`_safety_swaps`). Empty when the lineup is already
    # comfortable or when no admissible move helps.
    safety_swaps: list[SafetySwap] = field(default_factory=list)
    # Sign-up "User" names that matched NO member on the guild's member tab
    # (after case/space-insensitive matching) and were therefore ignored — a
    # data-quality signal the build surfaces loudly.
    unmatched_signups: list[str] = field(default_factory=list)
    # "<signup name> ≈ <member name>" for each sign-up matched only after
    # case/space normalisation (i.e. the two sheets disagree on capitalisation).
    normalized_matches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "week_date": self.week_date,
            "skills": self.skills,
            "cap": self.cap,
            "target_scale": self.target_scale,
            "roster_count": self.roster_count,
            "signup_count": self.signup_count,
            "non_signups": self.non_signups,
            "conflicts": self.conflicts,
            "enforced_total": self.enforced_total,
            "optimal_total": self.optimal_total,
            "gap": self.gap,
            "reachable_total": self.reachable_total,
            "min_slack_fraction": self.min_slack_fraction,
            "budget_seconds": self.budget_seconds,
            "safety_min_slack": self.safety_min_slack,
            "trials": [
                {
                    "skill": t.skill,
                    "party_size": t.party_size,
                    "tier_reached": t.tier_reached,
                    "points": t.points,
                    "open_seats": t.open_seats,
                    "clear_seconds": t.clear_seconds,
                    "slack_fraction": t.slack_fraction,
                    "clear_probability": t.clear_probability,
                    "roster": [asdict(r) for r in t.roster],
                }
                for t in self.trials
            ],
            "enforced_bench": self.enforced_bench,
            "optimal_summary": self.optimal_summary,
            "swaps": [asdict(s) for s in self.swaps],
            "safety_swaps": [asdict(s) for s in self.safety_swaps],
            "unmatched_signups": self.unmatched_signups,
            "normalized_matches": self.normalized_matches,
        }


# ---------------------------------------------------------------------------
# Core planning
# ---------------------------------------------------------------------------
def _sheet_column_for(trial_skill: str) -> str:
    """The config.SKILLS column name a trial skill maps to (Alchemy->Bell Farming)."""
    return config.TRIAL_SKILL_TO_SHEET_COLUMN.get(trial_skill, trial_skill)


def _locked_skill_of(
    picks: set[str], draw: list[str]
) -> Optional[str]:
    """Which drawn trial a member is locked into, or ``None`` if uncommitted.

    A member is locked into the FIRST drawn trial (in ``draw`` order) whose sheet
    column they ticked. Ticking more than one drawn trial is a conflict recorded
    by the caller; the first tick wins so the member is still placed.
    """
    for t in draw:
        if _sheet_column_for(t) in picks:
            return t
    return None


def _fill_open_seats(
    parties: list[set[int]],
    scorer: AssignmentScorer,
    free_pool: set[int],
    cap: int,
) -> tuple[list[set[int]], dict[int, tuple[int, int]]]:
    """Seat ``free_pool`` members into non-full parties, never lowering points.

    Mirrors :func:`src.optimizer._fill_bench` but restricted to the given free
    pool (the uncommitted members): repeatedly seats the (member, slot) with the
    greatest true Δpoints (>= 0), lowest member then lowest slot breaking ties,
    until every remaining free member would strictly lower some party's points.
    Because points are a STEP function of tier, a Δ == 0 rider crosses no
    threshold and does no harm, so they are welcomed aboard.

    Returns ``(parties, placed)`` where ``placed`` maps ``member_idx ->
    (slot_idx, gain)`` for each fill actually seated.
    """
    parties = [set(p) for p in parties]
    remaining = set(free_pool)
    placed: dict[int, tuple[int, int]] = {}
    S = len(scorer.skills)

    while remaining:
        best: Optional[tuple[int, int, int]] = None  # (gain, member, slot)
        for s in range(S):
            if len(parties[s]) >= cap:
                continue
            base = scorer.party_points(s, parties[s])
            for m in sorted(remaining):
                gain = scorer.party_points(s, parties[s] | {m}) - base
                if best is None or (gain, -m, -s) > (best[0], -best[1], -best[2]):
                    best = (gain, m, s)
        if best is None or best[0] < 0:
            break
        gain, m, s = best
        parties[s].add(m)
        remaining.discard(m)
        placed[m] = (s, gain)
    return parties, placed


def _single_move_climb(
    parties: list[set[int]],
    scorer: AssignmentScorer,
    cap: int,
    draw: list[str],
    members: list[MemberRow],
    swaps: list["Swap"],
    total: int,
) -> int:
    """Best-improvement single-move hill-climb, IN PLACE, recording each step.

    Mirrors :func:`src.optimizer._refine_hill_climb` — the same relocate + swap
    neighbourhood, best strictly-improving move each step — appending every
    applied move to ``swaps`` as a :class:`Swap` carrying the points it gains.
    Mutates ``parties`` and returns the updated ``total``. Deterministic (fixed
    scan order, no randomness). Stops at a local optimum (no single move helps).
    """
    from .optimizer import _relocate_delta, _swap_delta

    S = len(scorer.skills)
    n = len(scorer.members)

    for _ in range(config.OPT_HILLCLIMB_MAX_ITERS):
        assigned = {m: s for s in range(S) for m in parties[s]}
        best_delta = 0
        best_move: Optional[tuple] = None

        for m in range(n):
            a = assigned.get(m, -1)
            for b in range(-1, S):
                if b == a:
                    continue
                if b >= 0 and len(parties[b]) >= cap:
                    continue
                delta = _relocate_delta(scorer, parties, m, a, b)
                if delta > best_delta:
                    best_delta = delta
                    best_move = ("R", m, a, b)

        items = sorted(assigned.items())
        for i in range(len(items)):
            m1, a = items[i]
            for j in range(i + 1, len(items)):
                m2, b = items[j]
                if a == b:
                    continue
                delta = _swap_delta(scorer, parties, m1, a, m2, b)
                if delta > best_delta:
                    best_delta = delta
                    best_move = ("S", m1, a, m2, b)

        if best_move is None:
            break

        if best_move[0] == "R":
            _, m, a, b = best_move
            if a >= 0:
                parties[a].discard(m)
            if b >= 0:
                parties[b].add(m)
            name = members[m].name
            if a == -1:
                swaps.append(
                    Swap(name, "recruit", None, draw[b],
                         f"Recruit into {draw[b]}.", gain=best_delta)
                )
            elif b == -1:
                swaps.append(
                    Swap(name, "bench", draw[a], None,
                         f"Bench from {draw[a]} (headcount penalty).",
                         gain=best_delta)
                )
            else:
                swaps.append(
                    Swap(name, "move", draw[a], draw[b],
                         f"Move from {draw[a]} to {draw[b]}.", gain=best_delta)
                )
        else:
            _, m1, a, m2, b = best_move
            parties[a].discard(m1)
            parties[a].add(m2)
            parties[b].discard(m2)
            parties[b].add(m1)
            n1, n2 = members[m1].name, members[m2].name
            swaps.append(
                Swap(n1, "swap", draw[a], draw[b],
                     f"Swap {n1} ({draw[a]}) with {n2} ({draw[b]}).",
                     partner=n2, gain=best_delta)
            )
        total += best_delta

    return total


def _compound_reshuffle_into(
    parties: list[set[int]],
    s: int,
    scorer: AssignmentScorer,
    draw: list[str],
    members: list[MemberRow],
    target_tier: int,
) -> Optional[tuple[list[set[int]], "Swap"]]:
    """Cross one tier threshold in slot ``s`` via a short break-even swap run.

    Points are a STEP function of tier, so a single swap that upgrades a party's
    throughput usually crosses no threshold and scores Δ0 — which a strict
    single-move climb refuses, stranding the plan one tier below the optimum.
    This finds the *shortest* run of swaps into ``s`` that together lift it a
    tier, then records the whole run as one :class:`Swap` (``action ==
    "reshuffle"``) whose ``gain`` is the net points.

    Each step swaps a current ``s`` member out for an outsider in, requiring:

    * **Δpoints >= 0** for the swap (over the two touched parties) — so no trial
      ever regresses; the run's net gain is therefore exactly its final crossing.
    * a **strict rise** in ``s``'s throughput at ``target_tier`` — a monotone
      potential that both steers toward the threshold and guarantees termination.

    Returns ``(new_parties, swap)`` on success, or ``None`` if no crossing is
    reachable within a party's worth of swaps. Deterministic; ``parties`` is not
    mutated (a copy is returned).
    """
    from .optimizer import _swap_delta

    S = len(scorer.skills)
    parties = [set(p) for p in parties]
    base = scorer.total_points(parties)
    skill = draw[s]

    def throughput(members_in_s: set[int]) -> float:
        return sum(rate(members[m], skill, target_tier) for m in members_in_s)

    cur_phi = throughput(parties[s])
    moves: list[dict] = []

    # At most one full party's worth of replacements; the strict-φ guard means
    # each step is distinct, so this bound is never a silent truncation.
    for _ in range(len(parties[s]) + 1):
        best = None  # (sort_key, m_out, m_in, donor_slot, new_phi)
        for m_out in sorted(parties[s]):
            rate_out = rate(members[m_out], skill, target_tier)
            for b in range(S):
                if b == s:
                    continue
                for m_in in sorted(parties[b]):
                    delta = _swap_delta(scorer, parties, m_out, s, m_in, b)
                    if delta < 0:
                        continue  # never let any trial regress
                    new_phi = cur_phi - rate_out + rate(
                        members[m_in], skill, target_tier
                    )
                    if new_phi - cur_phi <= 1e-9:
                        continue  # require strict progress toward the threshold
                    # Prefer an immediate crossing (Δ), then most progress (Δφ),
                    # then lowest member indices — a fixed, deterministic order.
                    key = (delta, new_phi - cur_phi, -m_out, -m_in)
                    if best is None or key > best[0]:
                        best = (key, m_out, m_in, b, new_phi)
        if best is None:
            return None  # plateau has no break-even, progressing swap left

        _, m_out, m_in, b, new_phi = best
        parties[s].discard(m_out)
        parties[s].add(m_in)
        parties[b].discard(m_in)
        parties[b].add(m_out)
        moves.append(
            {
                "in": members[m_in].name,
                "out": members[m_out].name,
                "from_skill": draw[b],
            }
        )
        cur_phi = new_phi

        gain = scorer.total_points(parties) - base
        if gain > 0:
            ins = ", ".join(m["in"] for m in moves)
            outs = ", ".join(m["out"] for m in moves)
            n = len(moves)
            note = (
                f"Lift {skill} a tier (+{gain}) with {n} "
                f"swap{'s' if n != 1 else ''}: bring in {ins}; send out {outs}."
            )
            return parties, Swap(
                member=moves[-1]["in"],
                action="reshuffle",
                from_skill=None,
                to_skill=skill,
                note=note,
                gain=gain,
                moves=moves,
            )

    return None


def _improving_swaps(
    parties: list[set[int]],
    scorer: AssignmentScorer,
    cap: int,
    draw: list[str],
    members: list[MemberRow],
    optimal_points: Optional[dict[str, int]] = None,
    optimal_tier: Optional[dict[str, int]] = None,
) -> tuple[list["Swap"], int]:
    """Advisory strictly-improving moves from ``parties``, and their reachable total.

    Two phases, both recording every applied move as a :class:`Swap` (so each
    entry has ``gain > 0`` and ``reachable_total == start + sum(gains)``):

    1. A best-improvement **single-move** hill-climb (relocate + swap), exactly as
       before — cheap wins that improve on their own.
    2. When that stalls one or more tiers below the optimum, a **compound
       reshuffle** per under-tier trial: the shortest break-even swap run that
       crosses that trial's next tier (see :func:`_compound_reshuffle_into`).
       Points being a step function, this is the ONLY way to record the moves
       that close a tier gap — a strict single-move climb never can. After each
       reshuffle the single-move climb is re-run (the new roster may open fresh
       single wins), so the two phases interleave until nothing helps.

    Phase 2 runs only when ``optimal_points`` / ``optimal_tier`` (per trial skill)
    are supplied — the caller derives them from the optimal summary; without them
    the behaviour is the classic single-move climb. Deterministic throughout.
    """
    S = len(scorer.skills)
    parties = [set(p) for p in parties]
    swaps: list[Swap] = []
    total = scorer.total_points(parties)
    total = _single_move_climb(parties, scorer, cap, draw, members, swaps, total)

    if optimal_points is None or optimal_tier is None:
        return swaps, total

    # Phase 2: close remaining tier gaps trial-by-trial. Re-scan after every
    # reshuffle (a lift can unlock further single moves or another crossing);
    # the loop ends when no under-tier trial admits a break-even crossing.
    ceiling = sum(optimal_points.get(draw[s], 0) for s in range(S))
    while total < ceiling:
        progressed = False
        for s in range(S):
            skill = draw[s]
            target = optimal_points.get(skill)
            tier = optimal_tier.get(skill)
            if target is None or tier is None:
                continue
            if scorer.party_points(s, parties[s]) >= target:
                continue  # this trial already at (or above) its optimal tier
            result = _compound_reshuffle_into(
                parties, s, scorer, draw, members, tier
            )
            if result is None:
                continue
            parties, swap = result
            swaps.append(swap)
            total += swap.gain
            total = _single_move_climb(
                parties, scorer, cap, draw, members, swaps, total
            )
            progressed = True
            break  # restart the scan on the updated roster
        if not progressed:
            break

    return swaps, total


def _slack_key(pts: list[int], slack: list[float]) -> tuple[int, float, float]:
    """Lexicographic rank ``(total_points, min_margin, sum_margin)``.

    The same key :func:`src.optimizer._refine_slack` maximises, with ONE deliberate
    difference: the minimum is taken over the trials that actually BANK a tier. A
    trial scoring nothing has no margin to protect, and including its 0.0 would peg
    the minimum there and blind the max-min to every real improvement elsewhere.

    ``total_points`` comes first and is summed as the exact ``int`` it always was, so
    no candidate that costs a tier can ever outrank the incumbent.
    """
    banking = [q for p, q in zip(pts, slack) if p > 0]
    return (sum(pts), min(banking) if banking else 0.0, sum(slack))


def _safety_swaps(
    parties: list[set[int]],
    scorer: AssignmentScorer,
    cap: int,
    draw: list[str],
    members: list[MemberRow],
    free_pool: set[int],
    target: Optional[float] = None,
    max_moves: Optional[int] = None,
    allow_overrides: Optional[bool] = None,
) -> tuple[list[SafetySwap], Optional[float]]:
    """Advisory points-preserving moves that lift the thinnest trial off the buzzer.

    WHY A SEPARATE PASS. ``optimizer._refine_slack`` widens the margin of the
    UNCONSTRAINED optimum, and cannot be applied here: it would move locked
    volunteers, which this page promises never to do. So this is the same idea over
    the only neighbourhood the sign-up page actually controls — **where the
    uncommitted members sit**. Live motivation (SC, 2026-07-31): the enforced plan
    tied the 4900-point ceiling while Foraging held tier 12 by 65 seconds of 3600,
    against 18% for the optimum. Nothing in the points-based advice had a word to say
    about it, because on points there was nothing to say.

    THE SEARCH. Best-improvement local search over relocations (including to and from
    the bench) and swaps, ranked on :func:`_slack_key`. TWO acceptance conditions,
    both learned from a live probe that got them wrong (2026-07-31):

    * **The points must be EXACTLY equal.** Ranking points-first only guarantees a
      move never *costs* a tier; the probe promptly found one on LI that *gained* a
      tier (Alchemy 9 -> 10) while crashing that trial's margin 25.96% -> 0.23%, and
      reported it in a list captioned "same points, more margin". Points gains belong
      to :func:`_improving_swaps`, which finds that one anyway. Here they are
      excluded, so the caption is a guarantee rather than an aspiration.
    * **The MINIMUM must strictly rise.** Accepting any lexicographic improvement lets
      a move through on ``sum_margin`` alone. On SC the probe produced five such
      moves, every one leaving the thinnest trial at 1.81% — a page full of advice
      that fixed nothing. A move earns its place here only by lifting the thinnest
      trial itself; ``sum_margin`` survives purely to choose *between* moves that lift
      it equally.

    TWO PHASES. Phase 1 moves only ``free_pool`` (uncommitted) members, so no sign-up
    is overridden. If that cannot reach ``target`` — the SC case exactly: the thin
    trial was all volunteers, with no open seat to fill and nobody movable in it —
    phase 2 opens the whole roster and flags each such move ``overrides_signup``. The
    points swaps already override sign-ups when points justify it; this extends the
    same bargain to margin, but only after the cost-free options are exhausted, and
    always labelled. ``allow_overrides=False``
    (``config.SIGNUP_SAFETY_ALLOW_OVERRIDES``) stops after phase 1.

    Note that phase 2's pool is a SUPERSET, not a disjoint set: once it opens, a
    free-pool move may well follow an override, because phase 1 only exhausted the
    moves that helped *from the plan as it then stood*. What is guaranteed is that
    phase 1 is played out first, so ``allow_overrides=False`` returns exactly the
    leading, override-free stretch of the full run.

    Two stopping rules, both deliberate:

    * ``target`` (``config.SIGNUP_SAFETY_TARGET``): stop once the thinnest banking
      trial is comfortable. The pass exists to get off the buzzer, not to gold-plate
      a healthy lineup — and a healthy lineup therefore costs one scan and exits.
    * ``max_moves`` (``config.SIGNUP_SAFETY_MAX_MOVES``): a list nobody will carry
      out is worse than a short one. Anything needing more moves than this is a
      sign-up problem rather than a fill problem, and the page says so.

    Note the pass PREFERS relocation to benching without being told to: moving a
    member to another trial raises that trial's margin too, so it beats benching on
    the ``sum_margin`` tie-break. Benching wins only where the receiving trial would
    become the new thinnest — i.e. only where it genuinely buys more room.

    TERMINATION: the minimum strictly rises on every accepted move and is bounded
    above by ``target``, so no state can repeat; ``max_moves`` bounds the list length,
    not the correctness.

    Returns ``(moves, min_margin_after)``; ``min_margin_after`` is ``None`` when no
    trial banks a tier. Does not mutate ``parties``. Deterministic: fixed scan order,
    ties to the lowest indices.
    """
    if target is None:
        target = config.SIGNUP_SAFETY_TARGET
    if max_moves is None:
        max_moves = config.SIGNUP_SAFETY_MAX_MOVES
    if allow_overrides is None:
        allow_overrides = config.SIGNUP_SAFETY_ALLOW_OVERRIDES

    S = len(scorer.skills)
    parties = [set(p) for p in parties]
    n = len(scorer.members)
    volunteers = set(range(n)) - set(free_pool)
    moves: list[SafetySwap] = []

    def _state() -> tuple[list[int], list[float]]:
        pts = [scorer.party_points(s, parties[s]) for s in range(S)]
        slack = [scorer.party_slack(s, parties[s]) for s in range(S)]
        return pts, slack

    def _min_margin(pts: list[int], slack: list[float]) -> Optional[float]:
        banking = [q for p, q in zip(pts, slack) if p > 0]
        return min(banking) if banking else None

    def _best_move(movable: list[int], pts: list[int], slack: list[float]) -> Optional[tuple]:
        """The best points-EQUAL move that strictly raises the thinnest margin."""
        base_points, base_min, _ = _slack_key(pts, slack)
        assigned = {m: s for s in range(S) for m in parties[s]}

        def key_with(*changed: tuple[int, set]) -> tuple:
            p, q = list(pts), list(slack)
            for s, ids in changed:
                p[s] = scorer.party_points(s, ids)
                q[s] = scorer.party_slack(s, ids)
            return _slack_key(p, q)

        def admissible(key: tuple) -> bool:
            # Points exactly preserved (a gain is the OTHER list's business, and a
            # loss is never acceptable), and the thinnest trial strictly lifted.
            return key[0] == base_points and key[1] > base_min

        best_key: Optional[tuple] = None
        best: Optional[tuple] = None  # ("R", m, a, b) | ("S", m1, a, m2, b)

        # Relocations (bench included, both directions).
        for m in movable:
            a = assigned.get(m, -1)
            for b in range(-1, S):
                if b == a:
                    continue
                if b >= 0 and len(parties[b]) >= cap:
                    continue
                changed = []
                if a >= 0:
                    changed.append((a, parties[a] - {m}))
                if b >= 0:
                    changed.append((b, parties[b] | {m}))
                key = key_with(*changed)
                if admissible(key) and (best_key is None or key > best_key):
                    best_key, best = key, ("R", m, a, b)

        # Swaps between two seated movable members in different trials.
        seated = [(m, assigned[m]) for m in movable if m in assigned]
        for i in range(len(seated)):
            m1, a = seated[i]
            for j in range(i + 1, len(seated)):
                m2, b = seated[j]
                if a == b:
                    continue
                key = key_with(
                    (a, (parties[a] - {m1}) | {m2}),
                    (b, (parties[b] - {m2}) | {m1}),
                )
                if admissible(key) and (best_key is None or key > best_key):
                    best_key, best = key, ("S", m1, a, m2, b)

        return best

    # Phase 1 spends only the uncommitted members (no sign-up overridden); phase 2
    # opens the whole roster, and every move that touches a volunteer is flagged.
    phase_pools = [sorted(free_pool)]
    if allow_overrides:
        phase_pools.append(list(range(n)))

    for movable in phase_pools:
        while len(moves) < max_moves:
            pts, slack = _state()
            current_min = _min_margin(pts, slack)
            # Comfortable (or nothing banks a tier, in which case margin is not the
            # problem and the points advice above is where to look).
            if current_min is None or current_min >= target:
                break

            best_move = _best_move(movable, pts, slack)
            if best_move is None:
                break  # no permitted move lifts the thinnest trial

            # Apply, then describe the move by the margins it actually moved.
            touched: list[int] = []
            if best_move[0] == "R":
                _, m, a, b = best_move
                if a >= 0:
                    parties[a].discard(m)
                    touched.append(a)
                if b >= 0:
                    parties[b].add(m)
                    touched.append(b)
                name = members[m].name
                # Volunteers are never benched by construction, so any move of one
                # takes them out of the trial they ticked — an override either way.
                overrides = m in volunteers
                if a == -1:
                    action, from_skill, to_skill = "seat", None, draw[b]
                    note = f"Seat {name} (currently benched) into {draw[b]}."
                elif b == -1:
                    action, from_skill, to_skill = "bench", draw[a], None
                    note = (
                        f"Bench {name} from {draw[a]} — one head fewer lowers that "
                        f"trial's target by 1%. Costs {name} their share of the "
                        f"reward, so weigh it against the margin it buys."
                    )
                else:
                    action, from_skill, to_skill = "move", draw[a], draw[b]
                    note = f"Move {name} from {draw[a]} to {draw[b]}."
                swap = SafetySwap(
                    member=name, action=action, from_skill=from_skill,
                    to_skill=to_skill, note=note, overrides_signup=overrides,
                )
            else:
                _, m1, a, m2, b = best_move
                parties[a].discard(m1)
                parties[a].add(m2)
                parties[b].discard(m2)
                parties[b].add(m1)
                touched.extend([a, b])
                n1, n2 = members[m1].name, members[m2].name
                swap = SafetySwap(
                    member=n1, action="swap", from_skill=draw[a], to_skill=draw[b],
                    partner=n2,
                    note=f"Swap {n1} ({draw[a]}) with {n2} ({draw[b]}).",
                    overrides_signup=bool({m1, m2} & volunteers),
                )

            new_pts, new_slack = _state()
            swap.min_before = current_min
            swap.min_after = _min_margin(new_pts, new_slack) or 0.0
            swap.trial_changes = [
                {"skill": draw[s], "before": slack[s], "after": new_slack[s]}
                for s in sorted(set(touched))
                if new_slack[s] != slack[s]
            ]
            moves.append(swap)

    pts, slack = _state()
    return moves, _min_margin(pts, slack)


def plan(
    members: list[MemberRow],
    picks: dict[str, set[str]],
    optimal_total: int,
    optimal_summary: list[dict],
    draw: Optional[list[str]] = None,
    cap: Optional[int] = None,
    target_scale: Optional[float] = None,
) -> SignupPlan:
    """Build the enforced sign-up plan and its improving-swap advice.

    Args:
        members: the full guild roster (from the SC member tab).
        picks: ``{member_name: {sheet_skill_names_ticked}}`` (from
            :func:`parse_signup`); a member absent from this map is treated as
            having signed up for nothing.
        optimal_total: total guild points of the unconstrained full-roster
            optimum (the ceiling ``trials.html`` already computes) — reported
            for comparison.
        optimal_summary: per-trial ``{skill, tier_reached, points, party_size}``
            for that optimum (rendered alongside the enforced plan).
        draw / cap / target_scale: default to the shipped config values.
    """
    draw = list(draw if draw is not None else config.TRIAL_SKILLS_CURRENT)
    cap = cap if cap is not None else config.TRIAL_PARTY_CAP
    if target_scale is None:
        target_scale = config.TARGET_SCALE

    name_to_idx = {m.name: i for i, m in enumerate(members)}

    # --- Match sign-ups to members (exact, then case/space-insensitive) -----
    # Match each member's picks by EXACT name first, then fall back to a
    # normalised key (:func:`_norm_name` — casefold + collapsed whitespace) so a
    # sign-up that differs from the member tab only by capitalisation is still
    # honoured instead of silently dropped. A normalised key shared by two
    # DISTINCT members is ambiguous and matched exactly only (never merged).
    # Every sign-up whose name matches no member is collected for the build to
    # surface loudly (:attr:`SignupPlan.unmatched_signups`).
    member_names = {m.name for m in members}
    member_norm = [_norm_name(m.name) for m in members]
    ambiguous_keys = {k for k, c in Counter(member_norm).items() if c > 1}
    picks_by_norm: dict[str, set[str]] = {}
    picks_sources: dict[str, list[str]] = {}
    for user, ticks in picks.items():
        k = _norm_name(user)
        picks_by_norm.setdefault(k, set()).update(ticks)
        picks_sources.setdefault(k, []).append(user)

    normalized_matches: list[str] = []

    def _picks_for(idx: int, name: str) -> set[str]:
        """This member's ticked skills, joined exactly then case-insensitively."""
        if name in picks:  # exact match always wins
            return picks[name]
        k = member_norm[idx]
        if k not in ambiguous_keys and k in picks_by_norm:
            for src in picks_sources[k]:
                if src != name:
                    normalized_matches.append(f"{src} ≈ {name}")
            return picks_by_norm[k]
        return set()

    # --- Lock each volunteer into their chosen trial -----------------------
    locked: list[set[int]] = [set() for _ in draw]
    conflicts: list[str] = []
    signed_names: set[str] = set()
    for i, m in enumerate(members):
        member_picks = _picks_for(i, m.name)
        drawn_picks = [t for t in draw if _sheet_column_for(t) in member_picks]
        if not drawn_picks:
            continue
        if len(drawn_picks) > 1:
            conflicts.append(
                f"{m.name} ticked {', '.join(drawn_picks)} — locked into "
                f"{drawn_picks[0]} (first drawn choice)."
            )
        locked[draw.index(drawn_picks[0])].add(i)
        signed_names.add(m.name)

    # A sign-up is "matched" iff its name equals a member exactly OR its
    # normalised key is an UNAMBIGUOUS member key. Anything else joins to no
    # member and is reported (a typo, or a member missing from the roster tab).
    nonambiguous_member_keys = {
        k for k in set(member_norm) if k not in ambiguous_keys
    }
    unmatched_signups = sorted(
        user for user in picks
        if user not in member_names
        and _norm_name(user) not in nonambiguous_member_keys
    )

    non_signups = [m.name for m in members if m.name not in signed_names]
    free_pool = {name_to_idx[n] for n in non_signups}

    # --- Fill the open seats from the uncommitted pool ---------------------
    scorer = AssignmentScorer(members, draw, target_scale, cap)
    enforced, placed = _fill_open_seats(locked, scorer, free_pool, cap)

    # --- Build per-trial rosters (volunteers first, then recommended) ------
    trials: list[SignupTrial] = []
    enforced_slot: dict[int, Optional[int]] = {
        i: None for i in range(len(members))
    }
    for s, skill in enumerate(draw):
        party_idx = sorted(enforced[s])
        for i in party_idx:
            enforced_slot[i] = s
        party = [members[i] for i in party_idx]
        result = simulate_race(party, skill, target_scale)
        by_name = {r.name: r for r in result.roster}

        assigned_rows: list[SignupRosterEntry] = []
        rec_rows: list[SignupRosterEntry] = []
        for i in party_idx:
            m = members[i]
            r: RosterEntry = by_name[m.name]
            if i in locked[s]:
                assigned_rows.append(
                    SignupRosterEntry(
                        name=r.name, level=r.level, tool=r.tool, top=r.top,
                        bot=r.bot, rate_final=r.rate_final, status="assigned",
                    )
                )
            else:
                gain = placed.get(i, (s, 0))[1]
                rec_rows.append(
                    SignupRosterEntry(
                        name=r.name, level=r.level, tool=r.tool, top=r.top,
                        bot=r.bot, rate_final=r.rate_final, status="recommended",
                        fill_gain=gain, lifts_tier=gain > 0,
                    )
                )
        assigned_rows.sort(key=lambda e: e.rate_final, reverse=True)
        rec_rows.sort(key=lambda e: (e.fill_gain or 0, e.rate_final), reverse=True)

        trials.append(
            SignupTrial(
                skill=skill,
                party_size=result.party_size,
                tier_reached=result.tier_reached,
                points=result.points,
                open_seats=cap - result.party_size,
                roster=assigned_rows + rec_rows,
                # How narrowly this lineup banked its score. Free: read off the
                # simulate_race result already computed just above.
                clear_seconds=tier_clear_seconds(result),
                slack_fraction=time_slack_fraction(result),
                # The margin as odds. One extra pass over the party per trial
                # (four in total) — this is well outside the optimizer's hot loop.
                clear_probability=clear_probability(party, skill, result),
            )
        )

    enforced_total = sum(t.points for t in trials)
    scoring_slack = [t.slack_fraction for t in trials if t.tier_reached >= 1]
    min_slack_fraction = min(scoring_slack) if scoring_slack else None
    seated_free = {i for i in placed}
    enforced_bench = sorted(
        members[i].name for i in free_pool if i not in seated_free
    )

    # --- Advisory swaps: the minimal strictly-improving moves from here -----
    # A best-improvement hill-climb from the enforced plan, recording each move
    # and the points it gains. Unlike a diff against the arbitrary global
    # optimum (which reshuffles the whole guild for no net gain), every entry
    # here strictly raises the score, so the list is short and actionable. The
    # optimal per-trial tiers/points (from the summary) let a stalled climb cross
    # a tier plateau with a short break-even reshuffle — see _improving_swaps.
    optimal_points = {o["skill"]: o["points"] for o in optimal_summary}
    optimal_tier = {o["skill"]: o["tier_reached"] for o in optimal_summary}
    swaps, reachable_total = _improving_swaps(
        enforced, scorer, cap, draw, members,
        optimal_points=optimal_points, optimal_tier=optimal_tier,
    )

    # --- Advisory safety swaps: same points, more room ----------------------
    # Runs from the SHIPPED plan (``enforced``, which _improving_swaps copies rather
    # than mutates), independently of the points swaps above — the two lists are
    # alternatives an officer chooses between, not a sequence. Costs one scan and
    # exits when the lineup is already comfortable.
    safety_swaps, safety_min_slack = _safety_swaps(
        enforced, scorer, cap, draw, members, free_pool
    )

    now = datetime.now(timezone.utc)
    return SignupPlan(
        generated_at=now.isoformat(),
        week_date=now.strftime("%Y-%m-%d"),
        skills=draw,
        cap=cap,
        target_scale=target_scale,
        roster_count=len(members),
        signup_count=len(signed_names),
        non_signups=non_signups,
        conflicts=conflicts,
        enforced_total=enforced_total,
        optimal_total=optimal_total,
        gap=optimal_total - enforced_total,
        reachable_total=reachable_total,
        min_slack_fraction=min_slack_fraction,
        budget_seconds=config.TRIAL_TIME_BUDGET_SECONDS,
        safety_min_slack=safety_min_slack,
        trials=trials,
        enforced_bench=enforced_bench,
        optimal_summary=optimal_summary,
        swaps=swaps,
        safety_swaps=safety_swaps,
        unmatched_signups=unmatched_signups,
        normalized_matches=normalized_matches,
    )


def optimal_from_week(week) -> tuple[int, list[dict]]:
    """Adapt a :class:`src.trials.WeekResult` into ``plan``'s optimal inputs.

    Returns ``(optimal_total, optimal_summary)`` so the sign-up page reuses the
    exact optimum ``trials.html`` already computed — no second optimizer run,
    and the two pages never disagree on the ceiling.

    The summary also carries the optimum's own time margins (``clear_seconds`` /
    ``slack_fraction``), which is what the optimizer's safety pass deliberately
    maximised. Showing them beside the enforced plan's margins answers the question
    the points columns cannot: not just "how many points are we leaving on the
    table" but "how much safer than us is the assignment we could have had".
    """
    optimal_summary = [
        {
            "skill": t.skill,
            "tier_reached": t.tier_reached,
            "points": t.points,
            "party_size": t.party_size,
            "clear_seconds": tier_clear_seconds(t),
            "slack_fraction": time_slack_fraction(t),
            # Already attached by trials.run_week for the shipped races, so this
            # is a read rather than a recomputation.
            "clear_probability": t.clear_probability,
        }
        for t in week.trials
    ]
    return week.total_points, optimal_summary
