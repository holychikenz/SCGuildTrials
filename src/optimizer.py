"""Phase 2 guild-trials optimizer: assign members across the week's skilling
trials to maximise total guild points.

PURE LOGIC — no HTML, no network, no file I/O (mirrors :mod:`src.trials`). All
randomness is seeded via ``random.Random``; NEVER unseeded (repo convention, see
``config.TRIAL_RNG_SEED``).

Why this is not a plain assignment problem
------------------------------------------
The objective is total guild points::

    total(assignment) = sum_s points_for_tier(simulate_race(party_s, s).tier_reached)

which is both NON-linear and NON-separable, for two reasons documented in
``research/trial-messages.md``:

* **Points are a STEP function** of the tier reached (each tier ~ +100 pts),
  not a smooth per-member score.
* **The headcount penalty** (``effective_target`` grows 1% per member) means a
  weak member can *lower* a party's tier — so party SIZE is itself a decision
  variable and "fill every slot to 20" is not automatically optimal.

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
from .trials import Assignment, rate, simulate_race

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

    ``party_points`` is cached on ``(skill, frozenset(member_ids))`` because
    local search revisits the same party repeatedly; the cache turns an
    otherwise quadratic search into something a CI build tolerates. ``sim_calls``
    counts genuine (cache-missing) simulations so the bake-off can report the
    "how quickly" axis in oracle calls, independent of wall-clock noise.
    """

    def __init__(
        self,
        members: list[MemberRow],
        skills: list[str],
        target_scale: float,
        cap: int,
    ) -> None:
        self.members = members
        self.skills = skills
        self.target_scale = target_scale
        self.cap = cap
        self._cache: dict[tuple[str, frozenset], int] = {}
        self.sim_calls = 0

    def party_points(self, skill_idx: int, member_ids) -> int:
        """Points for the party ``member_ids`` running ``skills[skill_idx]``."""
        skill = self.skills[skill_idx]
        key = (skill, frozenset(member_ids))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        party = [self.members[i] for i in key[1]]
        self.sim_calls += 1
        pts = simulate_race(party, skill, self.target_scale).points
        self._cache[key] = pts
        return pts

    def total_points(self, parties: Parties) -> int:
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
    """
    return [
        [rate(members[m], skills[s], tier) for s in range(len(skills))]
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
        parties[s] = set(chunk)
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
        best: Optional[tuple[int, int, int]] = None  # (gain, member, slot)
        for s in range(S):
            if len(parties[s]) >= cap:
                continue
            for m in sorted(unassigned):
                gain = scorer.party_points(s, parties[s] | {m}) - base[s]
                if best is None or (gain, -m, -s) > (best[0], -best[1], -best[2]):
                    best = (gain, m, s)
        # Halt only when the best available placement would STRICTLY lower
        # points; gain-0 placements are kept to cross step-function plateaus.
        if best is None or best[0] < 0:
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

    def fitness(chrom: list[int]) -> int:
        return scorer.total_points(to_parties(chrom))

    def tournament(scored: list[tuple[int, list[int]]]) -> list[int]:
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
) -> int:
    """Δpoints of moving member ``m`` from slot ``a`` to slot ``b``.

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
) -> int:
    """Δpoints of swapping ``m1`` (in slot ``a``) with ``m2`` (in slot ``b``)."""
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
        best_delta = 0
        best_move: Optional[tuple] = None  # ("R", m, a, b) | ("S", m1, a, m2, b)

        # Relocations (including to/from the bench).
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

        # Swaps between members of two different slots.
        assigned_items = sorted(assigned.items())
        for i in range(len(assigned_items)):
            m1, a = assigned_items[i]
            for j in range(i + 1, len(assigned_items)):
                m2, b = assigned_items[j]
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
        else:
            _, m1, a, m2, b = best_move
            parties[a].discard(m1)
            parties[a].add(m2)
            parties[b].discard(m2)
            parties[b].add(m1)
    return parties


def _anneal_once(
    parties: Parties, scorer: AssignmentScorer, rng: random.Random
) -> tuple[Parties, int]:
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
                if b != a and (b < 0 or len(parties[b]) < cap)
            ]
            if not choices:
                continue
            b = rng.choice(choices)
            delta = _relocate_delta(scorer, parties, m, a, b)
            if delta >= 0 or rng.random() < math.exp(delta / temp):
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
            delta = _swap_delta(scorer, parties, m1, a, m2, b)
            if delta >= 0 or rng.random() < math.exp(delta / temp):
                parties[a].discard(m1)
                parties[a].add(m2)
                parties[b].discard(m2)
                parties[b].add(m1)
                cur += delta

        if cur > best:
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
        if cand_pts > best:
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

    Each pipeline gets its own derived seed for determinism; ties are broken by a
    canonical party key so the winner is stable run-to-run.
    """
    best_parties: Optional[Parties] = None
    best = -1
    for i, pipe in enumerate(config.OPT_ENSEMBLE_PIPELINES):
        parties = _run_pipeline(scorer, pipe, random.Random(seed + 1 + i))
        pts = scorer.total_points(parties)
        if (
            best_parties is None
            or pts > best
            or (
                pts == best
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
# Public API
# ---------------------------------------------------------------------------
def optimize(
    members: list[MemberRow],
    skills: list[str],
    seed: Optional[int] = None,
    cap: Optional[int] = None,
    target_scale: Optional[float] = None,
    strategy: Optional[str] = None,
) -> Assignment:
    """Assign ``members`` across ``skills`` to maximise total guild points.

    Deterministic given ``seed`` and ``strategy``. Returns an
    :class:`~src.trials.Assignment` (``MemberRow`` objects); members within each
    party and the bench are index-sorted so the output is stable. This is the
    Phase 2 replacement for :func:`src.trials.random_assignment`.
    """
    if seed is None:
        seed = config.TRIAL_OPTIMIZER_SEED
    if cap is None:
        cap = config.TRIAL_PARTY_CAP
    if target_scale is None:
        target_scale = config.TARGET_SCALE
    if strategy is None:
        strategy = config.TRIAL_OPTIMIZER_STRATEGY

    scorer = AssignmentScorer(members, skills, target_scale, cap)
    parties = run_strategy(scorer, strategy, seed)

    assigned: set[int] = set()
    party_map: dict[str, list[MemberRow]] = {}
    for s, skill in enumerate(skills):
        idxs = sorted(parties[s])
        party_map[skill] = [members[i] for i in idxs]
        assigned.update(idxs)
    bench = [members[i] for i in range(len(members)) if i not in assigned]
    return Assignment(parties=party_map, bench=bench)
