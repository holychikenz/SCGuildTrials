"""Phase 2 guild-trials optimizer: assign members across the week's skilling
trials to maximise total guild points.

PURE LOGIC — no HTML, no network, no file I/O (mirrors :mod:`src.trials`). All
randomness is seeded via ``random.Random``; NEVER unseeded (repo convention, see
``config.TRIAL_RNG_SEED``).

Why this is not a plain assignment problem
------------------------------------------
The objective is total guild points::

    total(assignment) = sum_s simulate_race(party_s, s).credit_points

which is both NON-linear and NON-separable, for two reasons documented in
``research/trial-messages.md``:

* **Points are PIECEWISE LINEAR WITH STEPS in the tier reached.** Since the
  2026-08-11 patch a trial is credited ``tier + 0.5 * progress_into_the_next_tier``
  (``config.TRIAL_PARTIAL_CREDIT_RATE``), so each tier is a ramp of ~50 points
  followed by a step of ~50 at the boundary. It was a pure step function of ~100
  points per tier, and much of this module was shaped by that: see
  :class:`AssignmentScorer` for what changed and
  ``research/partial-tier-credit.md`` for why.
* **The headcount penalty** (``effective_target`` grows 1% per member) means a
  weak member can *lower* a party's score — so party SIZE is itself a decision
  variable and "fill every slot" is not automatically optimal. This used to bite
  only when a member cost a whole tier; now it bites continuously, and the
  break-even is a member contributing about ``1/(100 + N)`` of the party's rate.

Consequently a classic linear-assignment solver (Hungarian) only optimises a
*proxy*; the true objective must be measured by calling ``simulate_race``. Every
strategy here is therefore judged against that real oracle (:class:`AssignmentScorer`),
and the bake-off in ``src/optimize_bakeoff.py`` selects the winner on points AND
speed.

Strategy grammar
----------------
A strategy string is ``constructor[+refiner[+refiner...]]`` — e.g.
``"proxy_greedy+hill_climb"`` or ``"marginal_greedy+sa"``. The first recognised
constructor token builds an initial assignment; each subsequent refiner improves
it in place. A bare refiner (no constructor token) defaults to a
``proxy_greedy`` seed.

  constructors: random, proxy_greedy, marginal_greedy, beam, genetic
  refiners:     hill_climb, sa
"""

from __future__ import annotations

import math
import random
from typing import Callable, Optional

from . import config
from .reader import MemberRow
from .trials import (
    Assignment,
    clear_probability,
    expected_credit_points,
    guild_building_skill_levels,
    meets_min_level,
    rate,
    simulate_race,
    time_slack_fraction,
)

# Sentinel for the reporting-only probability cache: None is a legitimate cached
# value there (a party that banks no tier), so absence needs its own marker.
_MISSING = object()


def _objective_value(party: list[MemberRow], skill: str, result) -> float:
    """The number every strategy in this module maximises, per config.OPT_OBJECTIVE.

    ONE function, called from exactly one place (:meth:`AssignmentScorer._evaluate`),
    so the whole search — constructors, refiners, the simulated annealer, the genetic
    pipeline, the bench fill, and ``src.signup``'s swap searches, which all reach the
    oracle through :meth:`AssignmentScorer.party_points` — cannot disagree about what
    it is optimising. See ``config.OPT_OBJECTIVE`` for why the default moved to the
    expectation and what it costs.

    ``expected_credit_points`` returns None for a party that cannot move or whose
    sigma cannot be derived. Those are exactly the parties whose deterministic score
    is 0.0 or near it, and falling back to ``credit_points`` for them is not a mixing
    of currencies but the limit the expectation takes as sigma vanishes: with no
    uncertainty to integrate over, E IS the deterministic score (asserted to 1e-9 in
    the tests).
    """
    if config.OPT_OBJECTIVE == "credit":
        return result.credit_points
    if config.OPT_OBJECTIVE != "expected":
        raise ValueError(
            f"config.OPT_OBJECTIVE must be 'expected' or 'credit', "
            f"not {config.OPT_OBJECTIVE!r}"
        )
    if not config.RISK_EXPECTED_POINTS:
        # Refused rather than degraded. RISK_EXPECTED_POINTS = False makes
        # expected_credit_points return None for EVERY party, so the fallback below
        # would silently turn the expected objective back into the deterministic one
        # while every comment, page and note still said otherwise.
        raise ValueError(
            "config.OPT_OBJECTIVE = 'expected' requires RISK_EXPECTED_POINTS = True; "
            "set OPT_OBJECTIVE = 'credit' to optimise the deterministic score."
        )
    expected = expected_credit_points(party, skill, result)
    return objective_of(result.credit_points, expected)


def objective_of(credit: float, expected: Optional[float]) -> float:
    """Pick the objective out of a (credit, expected) pair computed elsewhere.

    The same choice :func:`_objective_value` makes, for callers that already hold both
    numbers and must not pay for a second quadrature to re-derive one of them —
    ``src.signup``, which reads them off its own ``simulate_race`` results and off the
    optimum's summary dicts.

    THIS EXISTS SO THE SIGN-UP PAGE CANNOT MIX CURRENCIES. Its plan totals
    (``enforced_total``, ``optimal_total``, ``gap``) are compared directly against
    numbers that come from :meth:`AssignmentScorer.party_points` (``reachable_total``,
    every swap's gain, every fill's gain). Before this function they were credit on one
    side of the comparison and, once the objective moved, the expectation on the other
    — a page whose arithmetic silently stopped adding up. One selector, read by both
    sides, is what keeps ``reachable_total == enforced_total + sum(gains)`` an identity
    rather than an approximation.
    """
    if config.OPT_OBJECTIVE == "credit":
        return credit
    return credit if expected is None else expected

# Internal representation during search:
#   * members are referred to by their INDEX into the input ``members`` list;
#   * ``parties`` is a ``list[set[int]]`` aligned 1:1 with ``skills``;
#   * the bench is every index not present in any party.
# The public :func:`optimize` converts this back to an :class:`~src.trials.Assignment`
# of ``MemberRow`` objects at the boundary.
Parties = list  # list[set[int]]


# ---------------------------------------------------------------------------
# Scoring oracle (shared by every strategy AND the bake-off)
# ---------------------------------------------------------------------------
class AssignmentScorer:
    """Memoised bridge to :func:`src.trials.simulate_race`.

    Each party is cached on ``(skill, frozenset(member_ids))`` because local
    search revisits the same party repeatedly; the cache turns an otherwise
    quadratic search into something a CI build tolerates. ``sim_calls`` counts
    genuine (cache-missing) simulations so the bake-off can report the "how
    quickly" axis in oracle calls, independent of wall-clock noise.

    ONE simulation now yields TWO numbers, cached together: the party's points
    (the objective every strategy maximises) and its time-slack fraction (the
    tie-break the final pass maximises — see :func:`_refine_slack`). They share a
    cache entry because they come from the same ``simulate_race`` call, so slack
    costs no extra simulations at all.

    THE OBJECTIVE IS NOW ``E[credit_points]`` (2026-08-14), selected by
    ``config.OPT_OBJECTIVE`` and computed by :func:`_objective_value`. It was the
    deterministic ``credit_points``, which priced a tier held on a coin flip as a
    certainty and so kept buying tiers the party could not hold; see
    ``config.OPT_OBJECTIVE`` for the measurement that refuted
    ``research/partial-tier-credit.md`` §9.1's prediction that the two would agree.
    ``OPT_OBJECTIVE = "credit"`` is the one-line rollback and restores every
    trajectory below exactly. Note what this costs the cache: an entry is now ~3x
    dearer to fill (a quadrature on top of the race), so the memoisation this class
    exists for matters ~3x more than it did.

    THE OBJECTIVE BECAME A FLOAT earlier, with ``credit_points`` (game patch
    2026-08-11). It was ``simulate_race(...).points`` — an ``int``, a step function of
    the tier banked.
    Partial-tier credit made the score continuous, so :meth:`party_points` returns a
    ``float`` and callers must compare against ``config.OPT_POINTS_EPS`` rather than
    against 0. Two consequences worth stating plainly, because a great deal of this
    module's design was built on the old contract:

    * The plateaus are gone. ``research/risk-aware-objective.md`` R1 predicted this
      would make the existing search *strictly better* — "a move that buys 40 seconds
      toward the next tier is currently invisible; under Model 2 it is a positive
      delta" — so no constructor or refiner needs restructuring, only its comparisons.
    * Exact ties are gone with them, which is why :func:`_refine_slack` and
      ``signup._safety_swaps`` are re-founded on a stated points TOLERANCE instead of
      on integer equality.

    With ``config.TRIAL_PARTIAL_CREDIT_RATE`` at 0.0, ``credit_points`` is
    ``float(points)`` bit for bit and every strategy's trajectory is identical to the
    pre-patch code — the one-line rollback for all of it.
    """

    def __init__(
        self,
        members: list[MemberRow],
        skills: list[str],
        target_scale: float,
        cap: int,
        min_levels: Optional[dict[str, Optional[int]]] = None,
    ) -> None:
        self.members = members
        self.skills = skills
        self.target_scale = target_scale
        self.cap = cap
        # Per-trial minimum sign-up level (patch 2026-08-11), as the officers set it in
        # game. Resolved ONCE into a per-slot set of admissible member indices, because
        # every move generator in this module asks the question and it must be a set
        # lookup rather than a level comparison in the inner loop.
        #
        # None / absent -> unrestricted, so an unset minimum costs nothing and the
        # feature is inert until the officers fill the sheet cells in.
        self.min_levels = dict(min_levels or {})
        self._eligible: list[set[int]] = [
            {
                i
                for i, member in enumerate(members)
                if meets_min_level(member, skill, self.min_levels.get(skill))
            }
            for skill in skills
        ]
        self._cache: dict[tuple[str, frozenset], tuple[float, float, int]] = {}
        # Separate, reporting-only cache — see party_probability. None is a real
        # value here (no tier banked), so a sentinel marks "not yet computed".
        self._prob_cache: dict[tuple[str, frozenset], Optional[float]] = {}
        self.sim_calls = 0

    def _evaluate(self, skill_idx: int, member_ids) -> tuple[float, float, int]:
        """``(credit_points, time_slack_fraction, tier_reached)``, memoised.

        All three are read off the SAME ``simulate_race`` call, and partial-tier credit
        is computed inside the race from terms it already had, so this remains exactly
        one simulation per distinct party — ``sim_calls`` is unchanged by the patch.

        ``tier_reached`` joined the tuple on 2026-08-11 because the safety passes need
        to know which trials actually BANKED a tier, and since partial credit they can
        no longer infer it from the points: a party 30% into tier 1 scores 15 credit
        points while banking nothing at all. Points > 0 used to mean "banked"; now only
        the tier does.
        """
        skill = self.skills[skill_idx]
        key = (skill, frozenset(member_ids))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        party = [self.members[i] for i in key[1]]
        self.sim_calls += 1
        result = simulate_race(party, skill, self.target_scale)
        value = (
            _objective_value(party, skill, result),
            time_slack_fraction(result),
            result.tier_reached,
        )
        self._cache[key] = value
        return value

    def can_place(self, skill_idx: int, member: int) -> bool:
        """Whether ``member`` is permitted in ``skills[skill_idx]`` at all.

        A HARD constraint, not a preference: the game refuses the sign-up, so an
        ineligible member is not merely a poor choice but an impossible one. Every move
        generator consults this before proposing a placement, and :func:`optimize`
        filters again at the boundary — see the note there on why both.
        """
        return member in self._eligible[skill_idx]

    def eligible_members(self, skill_idx: int) -> set[int]:
        """The admissible member indices for one trial (a copy; callers may mutate)."""
        return set(self._eligible[skill_idx])

    def party_points(self, skill_idx: int, member_ids) -> float:
        """The OBJECTIVE for the party ``member_ids`` running ``skills[skill_idx]``.

        E[credit points] by default, the deterministic credit points under
        ``config.OPT_OBJECTIVE = "credit"`` — :func:`_objective_value` decides, and
        this is the only way any caller reaches it, so the whole search speaks one
        currency. The name is left as it was because every strategy, refiner and
        sign-up swap in the codebase calls it; what changed is which number it is,
        not what it means to a caller (bigger is better, deltas compare against
        ``config.OPT_POINTS_EPS`` and never against 0).

        A ``float`` either way. Under ``"credit"`` it is identical to
        ``float(simulate_race(...).points)`` when
        ``config.TRIAL_PARTIAL_CREDIT_RATE`` is 0.0.
        """
        return self._evaluate(skill_idx, member_ids)[0]

    def party_slack(self, skill_idx: int, member_ids) -> float:
        """Relative time margin by which that party held its tier (0 if none).

        See :func:`src.trials.time_slack_fraction`. Free: served from the same
        cache entry as :meth:`party_points`.
        """
        return self._evaluate(skill_idx, member_ids)[1]

    def party_tier(self, skill_idx: int, member_ids) -> int:
        """Highest tier this party actually BANKED (0 if none). Free, same cache entry.

        The honest test for "does this trial have a margin to protect?". Since partial
        credit, ``party_points > 0`` no longer answers that — see :meth:`_evaluate`.
        """
        return self._evaluate(skill_idx, member_ids)[2]

    def party_probability(self, skill_idx: int, member_ids) -> Optional[float]:
        """P(this party actually holds its tier). REPORTING ONLY — never the objective.

        Deliberately NOT folded into :meth:`_evaluate`'s cache tuple. That cache is
        the optimizer's hot path (~87k parties per pipeline) and
        :func:`trials.clear_probability` re-races the party to accumulate the Wald
        variance; paying that on every cache miss would dominate the build. This has
        its own cache and is called only by the handful of REPORTED states — the
        shipped lineup and each advisory safety swap.

        WHY THE SEARCH STILL RANKS ON MARGIN. Probability is monotone in margin for a
        fixed party, so on the dominant axis the two agree; where they differ is when
        a move also changes the party's own sigma, and there the honest answer is that
        the search's guarantee (points EXACTLY preserved, thinnest margin STRICTLY
        raised) is what makes a swap safe to recommend. Ranking on a noisier derived
        quantity would buy nothing and would silently change which swaps ship.
        """
        skill = self.skills[skill_idx]
        key = (skill, frozenset(member_ids))
        # NB the explicit default: a bare .get() returns None on a miss, which is
        # indistinguishable from a cached None ("this party banks no tier") and would
        # make every first call return None without computing anything.
        cached = self._prob_cache.get(key, _MISSING)
        if cached is not _MISSING:
            return cached
        party = [self.members[i] for i in key[1]]
        result = simulate_race(party, skill, self.target_scale)
        value = clear_probability(party, skill, result)
        self._prob_cache[key] = value
        return value

    def total_points(self, parties: Parties) -> float:
        """Total points across all parties (cache-backed, cheap to re-call)."""
        return sum(
            self.party_points(s, parties[s]) for s in range(len(self.skills))
        )


# ---------------------------------------------------------------------------
# Proxy scoring (cheap, static — used to seed/rank; NOT the true objective)
# ---------------------------------------------------------------------------
def _rate_matrix(
    members: list[MemberRow], skills: list[str], tier: int = 1
) -> list[list[float]]:
    """``rm[m][s]`` = member ``m``'s per-second work rate in ``skills[s]``.

    Evaluated at a representative low tier; a fast, linear stand-in for a
    member's affinity to a skill. Used only to order/seed strategies — the real
    objective is always ``AssignmentScorer``.

    The guild-building contribution is resolved once per skill rather than once
    per (member, skill) — same values, one lookup instead of ``len(members)``.
    """
    building = [guild_building_skill_levels(s) for s in skills]
    return [
        [
            rate(members[m], skills[s], tier, building[s])
            for s in range(len(skills))
        ]
        for m in range(len(members))
    ]


def _party_sort_key(parties: Parties) -> tuple:
    """Canonical, order-independent key for a set of parties (tie-breaking)."""
    return tuple(tuple(sorted(p)) for p in parties)


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------
def _construct_random(scorer: AssignmentScorer, rng: random.Random) -> Parties:
    """Shuffle-and-chunk, matching :func:`src.trials.random_assignment`.

    The control strategy: every other constructor must beat this.
    """
    n = len(scorer.members)
    order = list(range(n))
    rng.shuffle(order)
    parties: Parties = [set() for _ in scorer.skills]
    idx = 0
    for s in range(len(scorer.skills)):
        chunk = order[idx : idx + scorer.cap]
        # Drop anyone the trial's minimum sign-up level forbids. They are simply left
        # out rather than replaced: this is the control strategy, and topping the party
        # back up would quietly make it something better than random.
        parties[s] = {m for m in chunk if scorer.can_place(s, m)}
        idx += scorer.cap
    return parties


def _construct_proxy_greedy(
    scorer: AssignmentScorer, rng: random.Random
) -> Parties:
    """Strongest-first greedy on the static rate proxy.

    Members are handed a pick in descending order of their best per-skill rate;
    each takes their highest-rate non-full slot, and benches if they cannot
    contribute anywhere. Fast, deterministic, no oracle calls.
    """
    members, skills, cap = scorer.members, scorer.skills, scorer.cap
    rm = _rate_matrix(members, skills)
    parties: Parties = [set() for _ in skills]
    order = sorted(range(len(members)), key=lambda m: (-max(rm[m], default=0.0), m))
    for m in order:
        ranked = sorted(range(len(skills)), key=lambda s: (-rm[m][s], s))
        for s in ranked:
            if rm[m][s] <= 0:
                break  # no positive contribution anywhere -> bench
            if not scorer.can_place(s, m):
                continue  # below this trial's minimum sign-up level
            if len(parties[s]) < cap:
                parties[s].add(m)
                break
    return parties


def _construct_marginal_greedy(
    scorer: AssignmentScorer, rng: random.Random
) -> Parties:
    """Repeatedly place the (member, slot) with the greatest TRUE marginal Δpoints.

    Directly answers the headcount trade-off: a member is placed only where they
    do not *lower* points (gain >= 0), and a member who would only inflate the
    effective target everywhere (gain < 0) is left on the bench.

    Because points are a STEP function of tier, the immediate gain of a single
    placement is frequently ZERO — several members must join before a tier
    threshold is crossed. Stopping at the first zero-gain plateau would quit far
    too early, so the loop continues through gain-0 placements (which never hurt)
    and halts only when *every* remaining member would strictly reduce some
    party's points. The per-round scan recomputes only the slot that changed —
    every other column is served from the scorer cache — so this stays
    affordable despite calling the real simulator.
    """
    n = len(scorer.members)
    S = len(scorer.skills)
    cap = scorer.cap
    parties: Parties = [set() for _ in range(S)]
    unassigned = set(range(n))
    base = [scorer.party_points(s, parties[s]) for s in range(S)]

    while unassigned:
        best: Optional[tuple[float, int, int]] = None  # (gain, member, slot)
        for s in range(S):
            if len(parties[s]) >= cap:
                continue
            for m in sorted(unassigned):
                if not scorer.can_place(s, m):
                    continue
                gain = scorer.party_points(s, parties[s] | {m}) - base[s]
                if best is None or (gain, -m, -s) > (best[0], -best[1], -best[2]):
                    best = (gain, m, s)
        # Halt only when the best available placement would STRICTLY lower points.
        # Pre-2026-08-11 the objective was a step function of the tier, so gain-0
        # placements were common and had to be kept in order to cross those plateaus;
        # partial credit has turned the plateaus into slopes, so an exact zero is now
        # rare and this tolerance is float-noise insurance rather than a
        # plateau-crossing device.
        if best is None or best[0] < -config.OPT_POINTS_EPS:
            break
        _, m, s = best
        parties[s].add(m)
        unassigned.discard(m)
        base[s] = scorer.party_points(s, parties[s])
    return parties


def _construct_beam(scorer: AssignmentScorer, rng: random.Random) -> Parties:
    """Beam search: greedy placement keeping the top-K partial assignments.

    Members are considered strongest-first (proxy order). For each retained beam
    state a member may bench or join any non-full slot; states are scored by the
    true objective and pruned to ``OPT_BEAM_WIDTH``. Escapes the myopia of pure
    greedy at a modest, cache-amortised cost.
    """
    n = len(scorer.members)
    S = len(scorer.skills)
    cap = scorer.cap
    rm = _rate_matrix(scorer.members, scorer.skills)
    order = sorted(range(n), key=lambda m: (-max(rm[m], default=0.0), m))
    width = config.OPT_BEAM_WIDTH

    start: tuple = tuple(frozenset() for _ in range(S))
    beam: list[tuple] = [start]
    for m in order:
        seen: set = set()
        cands: list[tuple] = []
        for parties in beam:
            options = [parties]  # bench: no change
            for s in range(S):
                if not scorer.can_place(s, m):
                    continue
                if len(parties[s]) < cap:
                    nxt = list(parties)
                    nxt[s] = parties[s] | {m}
                    options.append(tuple(nxt))
            for opt in options:
                if opt not in seen:
                    seen.add(opt)
                    cands.append(opt)
        cands.sort(
            key=lambda p: (-scorer.total_points(list(p)), _party_sort_key(p))
        )
        beam = cands[:width]
    best = min(
        beam, key=lambda p: (-scorer.total_points(list(p)), _party_sort_key(p))
    )
    return [set(fs) for fs in best]


def _parties_to_chrom(parties: Parties, n: int) -> list[int]:
    """``parties`` -> ``slot_of[member]`` chromosome (``-1`` = benched)."""
    chrom = [-1] * n
    for s, party in enumerate(parties):
        for m in party:
            chrom[m] = s
    return chrom


def _run_genetic(
    scorer: AssignmentScorer,
    rng: random.Random,
    seed_parties: list[Parties],
) -> Parties:
    """Genetic algorithm over ``slot_of[member] in {-1,0..S-1}`` chromosomes.

    ``-1`` benches a member. A repair step enforces the per-slot cap (keeping the
    highest proxy-rate members, benching the rest). Fitness is the TRUE total
    points. Elitism + tournament selection + uniform crossover + point mutation;
    fully seeded for reproducibility.

    ``seed_parties`` injects strong starting solutions into the initial
    population (e.g. a beam-search result — a strong seed converges to a better
    optimum than an all-random population). The rest of the population is random.
    """
    n = len(scorer.members)
    S = len(scorer.skills)
    cap = scorer.cap
    rm = _rate_matrix(scorer.members, scorer.skills)

    def random_chrom() -> list[int]:
        return [rng.randint(-1, S - 1) for _ in range(n)]

    def repair(chrom: list[int]) -> list[int]:
        chrom = list(chrom)
        # Bench anyone the trial's minimum sign-up level forbids, BEFORE the cap trim,
        # so an ineligible member cannot displace an eligible one from a full party.
        for m in range(n):
            if chrom[m] >= 0 and not scorer.can_place(chrom[m], m):
                chrom[m] = -1
        for s in range(S):
            members_in = [m for m in range(n) if chrom[m] == s]
            if len(members_in) > cap:
                members_in.sort(key=lambda m: (-rm[m][s], m))
                for m in members_in[cap:]:
                    chrom[m] = -1
        return chrom

    def to_parties(chrom: list[int]) -> Parties:
        parties: Parties = [set() for _ in range(S)]
        for m in range(n):
            if chrom[m] >= 0:
                parties[chrom[m]].add(m)
        return parties

    def fitness(chrom: list[int]) -> float:
        return scorer.total_points(to_parties(chrom))

    def tournament(scored: list[tuple[float, list[int]]]) -> list[int]:
        k = config.OPT_GA_TOURNAMENT
        picks = [rng.randrange(len(scored)) for _ in range(k)]
        best_i = min(picks, key=lambda i: (-scored[i][0], i))
        return scored[best_i][1]

    pop_size = config.OPT_GA_POP
    population = [repair(_parties_to_chrom(p, n)) for p in seed_parties]
    while len(population) < pop_size:
        population.append(repair(random_chrom()))
    scored = [(fitness(c), c) for c in population]

    for _ in range(config.OPT_GA_GENERATIONS):
        scored.sort(key=lambda x: -x[0])
        newpop = [c for _, c in scored[: config.OPT_GA_ELITE]]
        while len(newpop) < pop_size:
            p1 = tournament(scored)
            p2 = tournament(scored)
            child = [p1[i] if rng.random() < 0.5 else p2[i] for i in range(n)]
            for i in range(n):
                if rng.random() < config.OPT_GA_MUTATION:
                    child[i] = rng.randint(-1, S - 1)
            newpop.append(repair(child))
        scored = [(fitness(c), c) for c in newpop]

    scored.sort(key=lambda x: -x[0])
    return to_parties(scored[0][1])


def _construct_genetic(scorer: AssignmentScorer, rng: random.Random) -> Parties:
    """Genetic algorithm seeded with the strong constructors (beam + greedies).

    Standalone constructor form: builds its own high-quality seed population from
    beam search, marginal-gain greedy and proxy greedy before evolving.
    """
    seeds = [
        _construct_beam(scorer, rng),
        _construct_marginal_greedy(scorer, rng),
        _construct_proxy_greedy(scorer, rng),
    ]
    return _run_genetic(scorer, rng, seeds)


def _refine_genetic(
    parties: Parties, scorer: AssignmentScorer, rng: random.Random
) -> Parties:
    """Genetic refiner: evolves a population seeded from the incoming assignment.

    Lets ``beam+genetic`` (or any ``constructor+genetic``) inject the constructor
    result as a strong founder alongside the greedy seeds — the beam-seeded GA
    the plan calls for.
    """
    seeds = [
        parties,
        _construct_marginal_greedy(scorer, rng),
        _construct_proxy_greedy(scorer, rng),
    ]
    return _run_genetic(scorer, rng, seeds)


# ---------------------------------------------------------------------------
# Incremental move deltas (shared by refiners)
# ---------------------------------------------------------------------------
def _relocate_delta(
    scorer: AssignmentScorer, parties: Parties, m: int, a: int, b: int
) -> float:
    """Δcredit-points of moving member ``m`` from slot ``a`` to slot ``b``.

    ``a`` or ``b`` may be ``-1`` (the bench), which scores 0. Only the two
    touched parties are (re)scored — both via the cache.
    """
    before = (scorer.party_points(a, parties[a]) if a >= 0 else 0) + (
        scorer.party_points(b, parties[b]) if b >= 0 else 0
    )
    after = (
        scorer.party_points(a, parties[a] - {m}) if a >= 0 else 0
    ) + (scorer.party_points(b, parties[b] | {m}) if b >= 0 else 0)
    return after - before


def _swap_delta(
    scorer: AssignmentScorer,
    parties: Parties,
    m1: int,
    a: int,
    m2: int,
    b: int,
) -> float:
    """Δcredit-points of swapping ``m1`` (in slot ``a``) with ``m2`` (in slot ``b``)."""
    before = scorer.party_points(a, parties[a]) + scorer.party_points(
        b, parties[b]
    )
    new_a = (parties[a] - {m1}) | {m2}
    new_b = (parties[b] - {m2}) | {m1}
    after = scorer.party_points(a, new_a) + scorer.party_points(b, new_b)
    return after - before


# ---------------------------------------------------------------------------
# Refiners
# ---------------------------------------------------------------------------
def _refine_hill_climb(
    parties: Parties, scorer: AssignmentScorer, rng: random.Random
) -> Parties:
    """Best-improvement local search over relocate + swap moves.

    Deterministic: candidate moves are scanned in a fixed order and the first
    strictly-best improving move is applied; iterates until no move helps or the
    iteration cap is hit. No randomness (the ``rng`` is accepted only for a
    uniform strategy signature).
    """
    S = len(scorer.skills)
    cap = scorer.cap
    n = len(scorer.members)
    parties = [set(p) for p in parties]

    for _ in range(config.OPT_HILLCLIMB_MAX_ITERS):
        assigned = {m: s for s in range(S) for m in parties[s]}
        # Was 0: with an integer objective "strictly improving" was exact. The
        # objective is continuous now, so a move must beat the incumbent by more than
        # float noise (see config.OPT_POINTS_EPS and trials._prepare_member on why an
        # ULP is not academic here).
        best_delta = config.OPT_POINTS_EPS
        best_move: Optional[tuple] = None  # ("R", m, a, b) | ("S", m1, a, m2, b)

        # Relocations (including to/from the bench).
        for m in range(n):
            a = assigned.get(m, -1)
            for b in range(-1, S):
                if b == a:
                    continue
                if b >= 0 and (
                    len(parties[b]) >= cap or not scorer.can_place(b, m)
                ):
                    continue
                delta = _relocate_delta(scorer, parties, m, a, b)
                if delta > best_delta:
                    best_delta = delta
                    best_move = ("R", m, a, b)

        # Swaps between members of two different slots.
        assigned_items = sorted(assigned.items())
        for i in range(len(assigned_items)):
            m1, a = assigned_items[i]
            for j in range(i + 1, len(assigned_items)):
                m2, b = assigned_items[j]
                if a == b:
                    continue
                if not (scorer.can_place(b, m1) and scorer.can_place(a, m2)):
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
        else:
            _, m1, a, m2, b = best_move
            parties[a].discard(m1)
            parties[a].add(m2)
            parties[b].discard(m2)
            parties[b].add(m1)
    return parties


def _anneal_once(
    parties: Parties, scorer: AssignmentScorer, rng: random.Random
) -> tuple[Parties, float]:
    """One annealing run from ``parties``; returns (best_parties, best_points).

    Geometric cooling from ``OPT_SA_T_START`` to ``OPT_SA_T_END`` over
    ``OPT_SA_ITERS`` steps; worsening moves accepted with probability
    ``exp(delta / T)``. Tracks the best assignment ever seen.
    """
    S = len(scorer.skills)
    cap = scorer.cap
    n = len(scorer.members)
    parties = [set(p) for p in parties]
    cur = scorer.total_points(parties)
    best = cur
    best_parties = [set(p) for p in parties]

    iters = config.OPT_SA_ITERS
    t0 = config.OPT_SA_T_START
    t1 = config.OPT_SA_T_END
    ratio = (t1 / t0) if t0 > 0 else 0.0

    for i in range(iters):
        temp = t0 * (ratio ** (i / max(1, iters - 1)))
        assigned = {m: s for s in range(S) for m in parties[s]}

        if rng.random() < 0.5:
            # Relocate a random member.
            m = rng.randrange(n)
            a = assigned.get(m, -1)
            choices = [
                b
                for b in range(-1, S)
                if b != a
                and (b < 0 or (len(parties[b]) < cap and scorer.can_place(b, m)))
            ]
            if not choices:
                continue
            b = rng.choice(choices)
            delta = _relocate_delta(scorer, parties, m, a, b)
            if delta >= -config.OPT_POINTS_EPS or rng.random() < math.exp(
                delta / temp
            ):
                if a >= 0:
                    parties[a].discard(m)
                if b >= 0:
                    parties[b].add(m)
                cur += delta
        else:
            # Swap two assigned members in different slots.
            assigned_items = list(assigned.items())
            if len(assigned_items) < 2:
                continue
            m1, a = rng.choice(assigned_items)
            m2, b = rng.choice(assigned_items)
            if a == b or m1 == m2:
                continue
            if not (scorer.can_place(b, m1) and scorer.can_place(a, m2)):
                continue
            delta = _swap_delta(scorer, parties, m1, a, m2, b)
            if delta >= -config.OPT_POINTS_EPS or rng.random() < math.exp(
                delta / temp
            ):
                parties[a].discard(m1)
                parties[a].add(m2)
                parties[b].discard(m2)
                parties[b].add(m1)
                cur += delta

        if cur > best + config.OPT_POINTS_EPS:
            best = cur
            best_parties = [set(p) for p in parties]
    return best_parties, best


def _refine_sa(
    parties: Parties, scorer: AssignmentScorer, rng: random.Random
) -> Parties:
    """Simulated annealing with multiple restarts (best kept).

    Runs ``OPT_SA_RESTARTS`` independent anneals from the same seed (each drawing
    a fresh random trajectory from the shared ``rng``) and returns the best — a
    cheap way to spend the daily-run's generous time budget on escaping distinct
    local optima. Fully seeded via ``rng``.
    """
    best_parties = [set(p) for p in parties]
    best = scorer.total_points(best_parties)
    for _ in range(max(1, config.OPT_SA_RESTARTS)):
        cand, cand_pts = _anneal_once(parties, scorer, rng)
        if cand_pts > best + config.OPT_POINTS_EPS:
            best = cand_pts
            best_parties = cand
    return best_parties


# ---------------------------------------------------------------------------
# Strategy registry + dispatch
# ---------------------------------------------------------------------------
_CONSTRUCTORS: dict[str, Callable[[AssignmentScorer, random.Random], Parties]] = {
    "random": _construct_random,
    "proxy_greedy": _construct_proxy_greedy,
    "marginal_greedy": _construct_marginal_greedy,
    "beam": _construct_beam,
    "genetic": _construct_genetic,
}

_REFINERS: dict[
    str, Callable[[Parties, AssignmentScorer, random.Random], Parties]
] = {
    "hill_climb": _refine_hill_climb,
    "sa": _refine_sa,
    "genetic": _refine_genetic,  # genetic doubles as a refiner (e.g. beam+genetic)
}

_DEFAULT_CONSTRUCTOR = "proxy_greedy"

# Ensemble aliases: run several strong pipelines and return the single best
# result. This is the correctness-first default — when the time budget allows,
# taking the max over diverse searches beats trusting any one method.
_ENSEMBLE_ALIASES = {"best", "ensemble"}


def parse_strategy(strategy: str) -> tuple[str, list[str]]:
    """Split a strategy string into ``(constructor, [refiners...])``.

    The FIRST token may be a constructor or a refiner (a leading refiner implies
    the default ``proxy_greedy`` seed); every subsequent token must be a refiner.
    ``genetic`` is both a constructor (self-seeding) and a refiner (beam+genetic).
    Raises ``ValueError`` on an unknown token so a typo fails loudly rather than
    silently falling back to random.
    """
    tokens = [t for t in strategy.split("+") if t]
    if not tokens:
        raise ValueError("empty optimizer strategy")

    first = tokens[0]
    if first in _CONSTRUCTORS:
        constructor = first
        rest = tokens[1:]
    elif first in _REFINERS:
        constructor = _DEFAULT_CONSTRUCTOR
        rest = tokens
    else:
        raise ValueError(
            f"unknown optimizer token {first!r} in strategy {strategy!r}; "
            f"constructors={sorted(_CONSTRUCTORS)}, refiners={sorted(_REFINERS)}"
        )
    for tok in rest:
        if tok not in _REFINERS:
            raise ValueError(
                f"token {tok!r} in strategy {strategy!r} is not a refiner; "
                f"refiners={sorted(_REFINERS)}"
            )
    return constructor, rest


def _run_pipeline(
    scorer: AssignmentScorer, strategy: str, rng: random.Random
) -> Parties:
    """Run one constructor+refiners pipeline with the given RNG."""
    constructor, refiners = parse_strategy(strategy)
    parties = _CONSTRUCTORS[constructor](scorer, rng)
    for ref in refiners:
        parties = _REFINERS[ref](parties, scorer, rng)
    return parties


def _run_ensemble(scorer: AssignmentScorer, seed: int) -> Parties:
    """Run every pipeline in ``config.OPT_ENSEMBLE_PIPELINES``; return the best.

    Each entry gets its own derived seed (``seed + 1 + i``) for determinism, which
    means a REPEATED pipeline is a genuine random restart rather than a duplicate
    of the same search — the shipped list is exactly that, ``OPT_RESTARTS`` copies
    of the strongest pipeline (see the live-data results in config: the variance
    that matters is between seeds, not between methods).

    Ties are broken by a canonical party key so the winner is stable run-to-run.
    """
    best_parties: Optional[Parties] = None
    best = -math.inf
    for i, pipe in enumerate(config.OPT_ENSEMBLE_PIPELINES):
        parties = _run_pipeline(scorer, pipe, random.Random(seed + 1 + i))
        pts = scorer.total_points(parties)
        # Float-safe since the objective became continuous: "strictly better" needs the
        # epsilon, and "tied" is a band rather than an equality. Two restarts that land
        # on the same assignment still tie exactly; two different assignments within
        # OPT_POINTS_EPS are treated as tied and settled by the canonical party key, so
        # the winner stays stable run to run.
        if (
            best_parties is None
            or pts > best + config.OPT_POINTS_EPS
            or (
                abs(pts - best) <= config.OPT_POINTS_EPS
                and _party_sort_key(parties) < _party_sort_key(best_parties)
            )
        ):
            best = pts
            best_parties = parties
    assert best_parties is not None  # OPT_ENSEMBLE_PIPELINES is never empty
    return best_parties


def run_strategy(
    scorer: AssignmentScorer, strategy: str, seed: int
) -> Parties:
    """Execute ``strategy`` against ``scorer`` and return the internal parties.

    Shared entry point for both :func:`optimize` and the bake-off harness so the
    two never diverge. ``"best"``/``"ensemble"`` dispatch to :func:`_run_ensemble`.
    """
    if strategy in _ENSEMBLE_ALIASES:
        return _run_ensemble(scorer, seed)
    return _run_pipeline(scorer, strategy, random.Random(seed))


# ---------------------------------------------------------------------------
# Final inclusion pass: seat the leftover bench, at a stated price
# ---------------------------------------------------------------------------
def _fill_bench(parties: Parties, scorer: AssignmentScorer) -> Parties:
    """Seat still-benched members in parties with room, for at most a stated cost.

    A pass applied AFTER the search has settled — outside any strategy, so the
    bake-off still measures strategies on their own merits. Members the search left
    benched are offered a seat in any non-full party where they cost no more than
    ``config.TRIAL_FILL_MAX_POINT_COST`` guild points (0.0 by default, i.e. no seat
    that costs anything).

    WHY THIS PASS CHANGED CHARACTER ON 2026-08-11. It used to be a free lunch, and
    said so: points were a STEP function of the tier, so "a member who crosses no
    threshold contributes exactly zero — no harm done — so they may as well come along
    for the ride". Hill-climb and SA apply only STRICT improvements and would never
    seat a Δ == 0 rider, so this pass existed purely to give those riders a seat that
    cost the guild nothing.

    Partial-tier credit abolished the free lunch. Every seat now raises the work target
    of *every* tier by 1% and moves the score measurably, so:

    * the search ALREADY seats everyone worth seating — a beneficial rider is now a
      strict improvement, which hill-climb takes on its own; and
    * what is left for this pass is the genuinely unprofitable rider, which is no
      longer a courtesy but a PURCHASE.

    So the pass survives as an explicit, priced subsidy rather than a no-regret
    tidy-up, and ``TRIAL_FILL_MAX_POINT_COST`` is the guild's dial for it. At the
    default 0.0 it seats only members who do not cost points at all, which is the
    honest continuation of the old promise; raise it to buy stragglers a share of the
    reward at a cost the sign-up page prints.

    Deterministic: repeatedly seats the (member, slot) with the greatest true
    Δpoints, lowest member then lowest slot index breaking ties (matching
    :func:`_construct_marginal_greedy`), until every remaining benched member would
    cost more than the subsidy allows. Cache-backed, so it stays cheap.
    """
    parties = [set(p) for p in parties]
    S = len(scorer.skills)
    cap = scorer.cap
    assigned: set[int] = set()
    for p in parties:
        assigned |= p
    benched = set(range(len(scorer.members))) - assigned

    while benched:
        best: Optional[tuple[float, int, int]] = None  # (gain, member, slot)
        for s in range(S):
            if len(parties[s]) >= cap:
                continue
            base = scorer.party_points(s, parties[s])
            for m in sorted(benched):
                if not scorer.can_place(s, m):
                    continue
                gain = scorer.party_points(s, parties[s] | {m}) - base
                if best is None or (gain, -m, -s) > (best[0], -best[1], -best[2]):
                    best = (gain, m, s)
        # Halt once the best available seat would cost more than the guild is
        # willing to pay. At TRIAL_FILL_MAX_POINT_COST == 0.0 this is "Δ >= 0", the
        # pre-patch rule; the epsilon keeps a float-noise Δ from reading as a cost.
        floor = -config.TRIAL_FILL_MAX_POINT_COST - config.OPT_POINTS_EPS
        if best is None or best[0] < floor:
            break
        _, m, s = best
        parties[s].add(m)
        benched.discard(m)
    return parties


# ---------------------------------------------------------------------------
# Final safety pass: buy time margin, at a stated price in points
# ---------------------------------------------------------------------------
# Float-noise guard on the MARGIN comparison, the counterpart of
# config.OPT_POINTS_EPS on the points. Margins are fractions of the hour, so a real
# improvement is many orders of magnitude larger than this; the epsilon exists only so
# that re-summing the same rosters in a different order cannot register as a "rise" and
# send the pass round another iteration.
_SLACK_EPS = 1e-12


def _min_banking(tiers: list[int], slack: list[float]) -> float:
    """Thinnest margin among the trials that actually BANKED a tier; 0.0 if none.

    Trials that banked nothing are EXCLUDED rather than counted as 0.0. Including them
    would peg the minimum at zero and blind a max-min search to every real improvement
    elsewhere — the lesson ``signup._slack_key`` already recorded, applied here so the
    two safety passes agree.

    Note the test is the TIER, not the points. Before partial credit the two were
    interchangeable (``points > 0`` iff a tier was banked); a party 30% into tier 1 now
    scores 15 credit points while banking nothing, so only the tier answers the
    question.
    """
    banking = [q for t, q in zip(tiers, slack) if t >= 1]
    return min(banking) if banking else 0.0
def _refine_slack(parties: Parties, scorer: AssignmentScorer) -> Parties:
    """Move members to lift the THINNEST trial's time margin, for almost no points.

    THE ORIGINAL PROBLEM. ``points`` was a step function of the tier reached, so the
    search was blind to *how narrowly* a tier was held. Measured on the live SC roster
    (2026-07-31, research/risk-aware-objective.md): 25 assignments all scoring exactly
    4900 points held their last tier by margins ranging from 100 seconds to 560 out of
    the 3600-second budget. A 100-second margin is 2.8% — thinner than the error on the
    model's own constants — so which of those assignments shipped was luck.

    WHAT PARTIAL CREDIT CHANGED (2026-08-11), because it is most of the original
    argument. The margin is no longer invisible to the objective: progress into the
    next tier IS the time left over, so ``credit_points`` now prices the margin
    linearly.

    IT DOES NOT FOLLOW THAT THE SEARCH WALKS OFF THE BUZZER BY ITSELF, and this
    docstring claimed that it did until the live run refuted it. The minimum margin did
    not improve — it **collapsed** to 0.09%, with three of eight live trials banking
    their tier 1–4 seconds inside the hour at ``P(holds) ≈ 0.51``. Pricing the margin
    linearly *within* a tier leaves a residual STEP of ``(1 - rho) * 100 = 50`` points at
    the boundary, which dwarfs any margin the search could buy by standing still — so the
    objective does not walk off the buzzer, it walks off *this* tier's buzzer and
    straight onto the *next* one's. Full treatment in
    ``research/partial-tier-credit.md`` §9.1. Two things follow:

    * The pass's original justification is NOT spent — the max-min problem is sharper
      than before, not softer. Its job is the part partial credit still cannot see: the
      objective is a **sum** over trials while risk is a **minimum** over them, so a
      lineup can bank a comfortable total while one trial sits on the boundary. This
      pass is the max-min correction to a max-sum search, and nothing else in the
      pipeline performs it. Expect it to find nothing on a knife-edge tier, though:
      ``config.OPT_SLACK_POINTS_TOLERANCE`` is 0.0 and stepping back to a comfortable
      lower tier costs ~55 points, so an empty result is the pass working, not failing.
    * Its old mechanism no longer works. It ranked on
      ``(total_points, min_slack, sum_slack)`` with the points "compared as exact ints,
      so it cannot trade a tier for margin" — a guarantee that came free from
      integrality. With a continuous objective exact ties barely exist, and that key
      would quietly degenerate into a duplicate of the hill-climb.

    THE PASS, RE-FOUNDED. Best-improvement local search over the SAME neighbourhood as
    :func:`_refine_hill_climb` (relocate, including to/from the bench, plus swap). A
    move is ADMISSIBLE iff both hold:

    * the total falls by at most ``config.OPT_SLACK_POINTS_TOLERANCE`` (0.0 by default,
      so by default it may not fall at all — the old guarantee, now stated rather than
      inherited from the type system); and
    * the thinnest margin **strictly rises**.

    Admissible moves are ranked ``(min_slack, sum_slack, total_points)``: lift the
    thinnest trial as far as possible, break ties on total margin, and prefer the
    variant that also keeps the most points.

    Both conditions are deliberate, and both were learned in ``signup._safety_swaps``,
    whose two-condition form this now matches. Requiring the minimum to rise *strictly*
    is what stops a move being accepted on ``sum_slack`` alone — a live probe once
    produced five such moves, every one leaving the thin trial exactly where it was.
    Unifying the two passes also removes an asymmetry the repo had already documented
    and regretted: the sign-up pass took its minimum over the trials that actually
    BANK a tier, while this one included a non-banking trial's 0.0 and let it peg the
    minimum, blinding the max-min to every real improvement elsewhere. This pass now
    does the same, via :meth:`AssignmentScorer.party_tier` — and note that since
    partial credit, "banked a tier" can no longer be inferred from "scored points".

    TERMINATION: every accepted move strictly raises a bounded quantity (the minimum
    margin) over a finite state space, so no state can repeat and no cycle can form.
    ``OPT_SLACK_MAX_ITERS`` is therefore a bound on worst-case build time, not a
    correctness requirement.

    COST: points, slack and tier all ride in the scorer's existing cache entry, so this
    adds no new simulations for any party the search already visited. Deterministic —
    moves are scanned in a fixed order and ties fall to the lowest indices.
    """
    S = len(scorer.skills)
    cap = scorer.cap
    n = len(scorer.members)
    parties = [set(p) for p in parties]

    for _ in range(config.OPT_SLACK_MAX_ITERS):
        pts = [scorer.party_points(s, parties[s]) for s in range(S)]
        slack = [scorer.party_slack(s, parties[s]) for s in range(S)]
        tiers = [scorer.party_tier(s, parties[s]) for s in range(S)]
        base_total = sum(pts)
        base_min = _min_banking(tiers, slack)
        # The most the total may fall. Stated once, here, so the pass's price is a
        # config decision rather than an artefact of how points are represented.
        floor = (
            base_total
            - config.OPT_SLACK_POINTS_TOLERANCE
            - config.OPT_POINTS_EPS
        )
        assigned = {m: s for s in range(S) for m in parties[s]}

        def state_with(*changed: tuple[int, set]) -> tuple[float, float, float]:
            """``(total, min_banking_slack, sum_slack)`` after replacing those slots."""
            p, q, t = list(pts), list(slack), list(tiers)
            for s, ids in changed:
                p[s] = scorer.party_points(s, ids)
                q[s] = scorer.party_slack(s, ids)
                t[s] = scorer.party_tier(s, ids)
            return sum(p), _min_banking(t, q), sum(q)

        def rank(state: tuple[float, float, float]) -> Optional[tuple]:
            """Rank key for an ADMISSIBLE move, or None if it is not admissible.

            Admissible = costs at most the tolerance AND strictly lifts the thinnest
            banking trial. Ranked thinnest-first, then total margin, then points.
            """
            total, min_slack, sum_slack = state
            if total < floor:
                return None
            if min_slack <= base_min + _SLACK_EPS:
                return None
            return (min_slack, sum_slack, total)

        best_key: Optional[tuple] = None
        best_move: Optional[tuple] = None  # ("R", m, a, b) | ("S", m1, a, m2, b)

        # Relocations (including to and from the bench).
        for m in range(n):
            a = assigned.get(m, -1)
            for b in range(-1, S):
                if b == a:
                    continue
                if b >= 0 and (
                    len(parties[b]) >= cap or not scorer.can_place(b, m)
                ):
                    continue
                changed = []
                if a >= 0:
                    changed.append((a, parties[a] - {m}))
                if b >= 0:
                    changed.append((b, parties[b] | {m}))
                key = rank(state_with(*changed))
                if key is not None and (best_key is None or key > best_key):
                    best_key = key
                    best_move = ("R", m, a, b)

        # Swaps between members of two different slots.
        assigned_items = sorted(assigned.items())
        for i in range(len(assigned_items)):
            m1, a = assigned_items[i]
            for j in range(i + 1, len(assigned_items)):
                m2, b = assigned_items[j]
                if a == b:
                    continue
                if not (scorer.can_place(b, m1) and scorer.can_place(a, m2)):
                    continue
                key = rank(
                    state_with(
                        (a, (parties[a] - {m1}) | {m2}),
                        (b, (parties[b] - {m2}) | {m1}),
                    )
                )
                if key is not None and (best_key is None or key > best_key):
                    best_key = key
                    best_move = ("S", m1, a, m2, b)

        if best_move is None:
            break
        if best_move[0] == "R":
            _, m, a, b = best_move
            if a >= 0:
                parties[a].discard(m)
            if b >= 0:
                parties[b].add(m)
        else:
            _, m1, a, m2, b = best_move
            parties[a].discard(m1)
            parties[a].add(m2)
            parties[b].discard(m2)
            parties[b].add(m1)
    return parties


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def optimize(
    members: list[MemberRow],
    skills: list[str],
    seed: Optional[int] = None,
    cap: Optional[int] = None,
    target_scale: Optional[float] = None,
    strategy: Optional[str] = None,
    min_levels: Optional[dict[str, Optional[int]]] = None,
) -> Assignment:
    """Assign ``members`` across ``skills`` to maximise total guild points.

    Deterministic given ``seed`` and ``strategy``. Returns an
    :class:`~src.trials.Assignment` (``MemberRow`` objects); members within each
    party and the bench are index-sorted so the output is stable. This is the
    Phase 2 replacement for :func:`src.trials.random_assignment`.

    ``min_levels`` carries each trial's minimum sign-up level as the officers set it in
    game (patch 2026-08-11); ``None`` or an absent skill means unrestricted, so the
    default behaviour is exactly as before.
    """
    if seed is None:
        seed = config.TRIAL_OPTIMIZER_SEED
    if cap is None:
        cap = config.TRIAL_PARTY_CAP
    if target_scale is None:
        target_scale = config.TARGET_SCALE
    if strategy is None:
        strategy = config.TRIAL_OPTIMIZER_STRATEGY

    scorer = AssignmentScorer(members, skills, target_scale, cap, min_levels)
    parties = run_strategy(scorer, strategy, seed)
    # Inclusion pass, then the safety pass. ORDER REVERSED 2026-08-11, and the reversal
    # is forced by partial credit.
    #
    # It used to run the other way round — safety first, inclusion LAST — on the
    # argument that "inclusion outranks margin": the safety pass would bench a member
    # to buy margin (each head is 1% of the work target) and on the live LI roster it
    # cut three, and re-seating them afterwards cost 1.2pp of the minimum margin
    # (634s -> 591s, measured 2026-07-31) and NO POINTS AT ALL. That last clause was
    # the whole justification, and partial credit has retired it: a re-seated rider now
    # moves the score, so seating one after the safety pass would spend points the
    # safety pass had just been forbidden to spend, silently and outside its budget.
    #
    # Running inclusion FIRST keeps every decision in the currency it belongs to:
    # _fill_bench decides who travels, on points, against its own stated subsidy
    # (TRIAL_FILL_MAX_POINT_COST); _refine_slack then chooses the safest arrangement of
    # whoever is aboard, against its own stated tolerance. Neither can raid the other's
    # budget.
    parties = _fill_bench(parties, scorer)
    # Safety pass: among the arrangements worth (almost) these same points, take the
    # one whose THINNEST trial has the most time to spare. OPT_SLACK_PASS = False
    # disables it; OPT_SLACK_POINTS_TOLERANCE = 0.0 forbids it from spending anything.
    if config.OPT_SLACK_PASS:
        parties = _refine_slack(parties, scorer)

    # BELT AND BRACES on the minimum sign-up level. Every move generator above already
    # refuses an ineligible placement, and under the post-patch objective a member the
    # game would reject is usually unattractive anyway — but "the search would not have
    # chosen it" is a property of the search, not a guarantee about the output, and this
    # is a HARD game constraint: a party containing an ineligible member is one the
    # guild cannot actually field. So it is enforced once more at the boundary, where it
    # is cheap and unconditional.
    parties = [
        {m for m in parties[s] if scorer.can_place(s, m)}
        for s in range(len(skills))
    ]

    assigned: set[int] = set()
    party_map: dict[str, list[MemberRow]] = {}
    for s, skill in enumerate(skills):
        idxs = sorted(parties[s])
        party_map[skill] = [members[i] for i in idxs]
        assigned.update(idxs)
    bench = [members[i] for i in range(len(members)) if i not in assigned]
    return Assignment(parties=party_map, bench=bench)
