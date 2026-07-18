"""Unit tests for the Phase 2 guild-trials optimizer. No network access.

Covers the memoised scoring oracle's fidelity, per-strategy determinism and
constraint-validity (partition, cap, no duplicates), the "never worse than
random / never worse than its seed" regressions, and the headcount trade-off
(a straggler that lowers a tier is left on the bench).
"""

import random

import pytest

from src import config, optimizer, trials
from src.reader import MemberRow, SkillEntry


# ---------------------------------------------------------------------------
# Budget: the shipped config sizes the metaheuristics for a daily CI run (many
# thousands of SA iters, GA generations). Tests only assert RELATIVE properties
# (>= random, >= seed, determinism, validity) which hold at any budget, so shrink
# the knobs to keep the suite fast. Determinism is preserved (still fully seeded).
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _fast_optimizer_budget(monkeypatch):
    monkeypatch.setattr(config, "OPT_SA_ITERS", 1500)
    monkeypatch.setattr(config, "OPT_SA_RESTARTS", 1)
    monkeypatch.setattr(config, "OPT_GA_POP", 20)
    monkeypatch.setattr(config, "OPT_GA_GENERATIONS", 25)
    monkeypatch.setattr(config, "OPT_BEAM_WIDTH", 6)
    monkeypatch.setattr(config, "OPT_HILLCLIMB_MAX_ITERS", 100)


# ---------------------------------------------------------------------------
# Fixtures (inline; nothing here touches Google Sheets)
# ---------------------------------------------------------------------------
def _member(name, levels=None, checks=None):
    levels = levels or {}
    checks = checks or {}
    skills = {}
    for sk in config.SKILLS:
        tool, top, bot = checks.get(sk, (False, False, False))
        skills[sk] = SkillEntry(
            level=levels.get(sk, 100), tool=tool, top=top, bot=bot
        )
    return MemberRow(
        name=name, main_classes="", flex="", flex_levels=[], skills=skills
    )


def _roster(n, seed=7):
    """A varied roster with a real level spread (some stragglers)."""
    rng = random.Random(seed)
    members = []
    for i in range(n):
        levels = {}
        for sk in config.SKILLS:
            levels[sk] = rng.randint(70, 140)
        members.append(_member(f"m{i:03d}", levels))
    return members


SKILLS = ["Foraging", "Woodcutting", "Alchemy", "Enhancing"]

# Every non-random constructor + representative pairings + the ensemble default.
ALL_STRATEGIES = [
    "random",
    "proxy_greedy",
    "marginal_greedy",
    "beam",
    "genetic",
    "proxy_greedy+hill_climb",
    "proxy_greedy+sa",
    "marginal_greedy+hill_climb",
    "marginal_greedy+sa",
    "beam+genetic+hill_climb",
    "best",
]


# ---------------------------------------------------------------------------
# Scorer fidelity
# ---------------------------------------------------------------------------
def test_scorer_cache_matches_fresh():
    members = _roster(24)
    a = optimizer.AssignmentScorer(members, SKILLS, config.TARGET_SCALE, 20)
    b = optimizer.AssignmentScorer(members, SKILLS, config.TARGET_SCALE, 20)
    parties = [set(range(0, 6)), set(range(6, 12)), set(range(12, 18)), set(range(18, 24))]

    first = a.party_points(0, parties[0])
    second = a.party_points(0, parties[0])  # cache hit
    assert first == second
    assert a.sim_calls == 1  # the second call did not re-simulate

    # Cached total equals an independent fresh scorer's total.
    assert a.total_points(parties) == b.total_points(parties)


def test_scorer_total_matches_simulate_race_directly():
    members = _roster(16)
    scorer = optimizer.AssignmentScorer(members, SKILLS, config.TARGET_SCALE, 20)
    parties = [set(range(0, 4)), set(range(4, 8)), set(range(8, 12)), set(range(12, 16))]
    expected = 0
    for s, skill in enumerate(SKILLS):
        party = [members[i] for i in sorted(parties[s])]
        expected += trials.simulate_race(party, skill, config.TARGET_SCALE).points
    assert scorer.total_points(parties) == expected


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("strategy", ALL_STRATEGIES)
def test_strategy_deterministic(strategy):
    members = _roster(40)
    a1 = optimizer.optimize(members, SKILLS, seed=99, strategy=strategy)
    a2 = optimizer.optimize(members, SKILLS, seed=99, strategy=strategy)
    for sk in SKILLS:
        assert [m.name for m in a1.parties[sk]] == [m.name for m in a2.parties[sk]]
    assert [m.name for m in a1.bench] == [m.name for m in a2.bench]


# ---------------------------------------------------------------------------
# Constraint validity
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("strategy", ALL_STRATEGIES)
def test_assignment_is_a_valid_partition(strategy):
    members = _roster(86)
    asn = optimizer.optimize(members, SKILLS, seed=3, cap=20, strategy=strategy)

    assigned = [m.name for p in asn.parties.values() for m in p]
    bench = [m.name for m in asn.bench]
    # No member appears twice; every member is either assigned or benched.
    assert len(assigned) == len(set(assigned))
    assert set(assigned) | set(bench) == {m.name for m in members}
    assert set(assigned) & set(bench) == set()
    # Cap respected on every slot.
    assert all(len(p) <= 20 for p in asn.parties.values())


# ---------------------------------------------------------------------------
# Quality regressions
# ---------------------------------------------------------------------------
def _total_points(members, skills, asn, target_scale=None):
    if target_scale is None:
        target_scale = config.TARGET_SCALE
    return sum(
        trials.simulate_race(asn.parties[sk], sk, target_scale).points
        for sk in skills
    )


@pytest.mark.parametrize(
    "strategy",
    [s for s in ALL_STRATEGIES if s != "random"],
)
def test_optimizer_beats_or_ties_random(strategy):
    members = _roster(86, seed=11)
    rnd = trials.random_assignment(members, SKILLS, seed=42, cap=20)
    opt = optimizer.optimize(members, SKILLS, seed=5, cap=20, strategy=strategy)
    rnd_pts = _total_points(members, SKILLS, rnd)
    opt_pts = _total_points(members, SKILLS, opt)
    assert opt_pts >= rnd_pts


def test_ensemble_at_least_matches_a_deterministic_seed():
    # "best" includes a pipeline seeded by the DETERMINISTIC proxy_greedy
    # constructor whose refiners can only improve it, and returns the max over
    # all pipelines -> it can never score below proxy_greedy alone.
    members = _roster(70, seed=23)
    best = optimizer.optimize(members, SKILLS, seed=8, strategy="best")
    seed_only = optimizer.optimize(members, SKILLS, seed=8, strategy="proxy_greedy")
    assert _total_points(members, SKILLS, best) >= _total_points(
        members, SKILLS, seed_only
    )


@pytest.mark.parametrize("refiner", ["hill_climb", "sa"])
def test_refiner_never_worse_than_its_seed(refiner):
    members = _roster(60, seed=13)
    seed_asn = optimizer.optimize(members, SKILLS, seed=5, strategy="proxy_greedy")
    refined = optimizer.optimize(
        members, SKILLS, seed=5, strategy=f"proxy_greedy+{refiner}"
    )
    assert _total_points(members, SKILLS, refined) >= _total_points(
        members, SKILLS, seed_asn
    )


def test_headcount_deadweight_never_lowers_result():
    # A rate-0 deadweight (level 0 -> success clamps to 0, contributes nothing)
    # only inflates the 1%/member target. A true-objective optimizer must never
    # let it drag the result below the strong-only arrangement: either bench it,
    # or include it only where harmless.
    strong = [
        _member(f"s{i}", {"Foraging": 135}, {"Foraging": (True, True, True)})
        for i in range(12)
    ]
    deadweight = _member("dead", {"Foraging": 0})
    deadweight.skills["Foraging"] = SkillEntry(
        level=0, tool=False, top=False, bot=False
    )
    members = strong + [deadweight]
    skills = ["Foraging"]

    strong_only = trials.simulate_race(strong, "Foraging").points
    all_in = trials.simulate_race(members, "Foraging").points
    assert all_in <= strong_only  # sanity: deadweight cannot help

    for strat in ["marginal_greedy", "marginal_greedy+hill_climb", "proxy_greedy+sa"]:
        asn = optimizer.optimize(members, skills, seed=1, strategy=strat)
        got = _total_points(members, skills, asn)
        assert got >= strong_only, f"{strat} dragged below strong-only"


# ---------------------------------------------------------------------------
# Final bench-fill courtesy pass
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("strategy", ALL_STRATEGIES)
def test_no_free_rider_left_behind(strategy):
    # After optimize, every benched member must be genuinely deadweight: adding
    # them to ANY non-full party would strictly lower that party's points. If a
    # zero-or-positive seat existed, the fill pass should have taken it.
    members = _roster(86, seed=29)
    asn = optimizer.optimize(members, SKILLS, seed=4, cap=20, strategy=strategy)

    name_to_member = {m.name: m for m in members}
    scorer = optimizer.AssignmentScorer(members, SKILLS, config.TARGET_SCALE, 20)
    party_ids = {
        s: {members.index(name_to_member[m.name]) for m in asn.parties[sk]}
        for s, sk in enumerate(SKILLS)
    }
    for benched in asn.bench:
        bi = members.index(name_to_member[benched.name])
        for s, sk in enumerate(SKILLS):
            if len(party_ids[s]) >= 20:
                continue
            base = scorer.party_points(s, party_ids[s])
            withm = scorer.party_points(s, party_ids[s] | {bi})
            assert withm - base < 0, (
                f"{benched.name} could have joined {sk} at no cost ({strategy})"
            )


def test_fill_bench_never_lowers_total_and_only_adds():
    # Start from a deliberately under-filled assignment (everyone benched) and
    # let the courtesy pass seat people. It must never lower the total and must
    # only ADD members to parties (never remove or reshuffle).
    members = _roster(40, seed=31)
    scorer = optimizer.AssignmentScorer(members, SKILLS, config.TARGET_SCALE, 20)
    empty = [set() for _ in SKILLS]

    before = scorer.total_points(empty)  # 0
    filled = optimizer._fill_bench(empty, scorer)
    after = scorer.total_points(filled)

    assert after >= before
    # No member appears twice; the cap is respected.
    all_ids = [m for p in filled for m in p]
    assert len(all_ids) == len(set(all_ids))
    assert all(len(p) <= 20 for p in filled)
    # Terminal invariant: no benched member could still join at Δ >= 0.
    benched = set(range(len(members))) - set(all_ids)
    for s in range(len(SKILLS)):
        if len(filled[s]) >= 20:
            continue
        base = scorer.party_points(s, filled[s])
        for bi in benched:
            assert scorer.party_points(s, filled[s] | {bi}) - base < 0


# ---------------------------------------------------------------------------
# Strategy parsing
# ---------------------------------------------------------------------------
def test_parse_strategy_constructor_and_refiners():
    assert optimizer.parse_strategy("marginal_greedy+hill_climb") == (
        "marginal_greedy",
        ["hill_climb"],
    )
    assert optimizer.parse_strategy("proxy_greedy") == ("proxy_greedy", [])
    # Bare refiner defaults to the proxy_greedy seed.
    assert optimizer.parse_strategy("sa") == ("proxy_greedy", ["sa"])


def test_parse_strategy_genetic_is_constructor_and_refiner():
    # genetic leading -> constructor; genetic after a constructor -> refiner.
    assert optimizer.parse_strategy("genetic") == ("genetic", [])
    assert optimizer.parse_strategy("beam+genetic+hill_climb") == (
        "beam",
        ["genetic", "hill_climb"],
    )


def test_parse_strategy_rejects_unknown_token():
    with pytest.raises(ValueError):
        optimizer.parse_strategy("teleportation")
    with pytest.raises(ValueError):
        # beam is a constructor, never valid as a trailing refiner.
        optimizer.parse_strategy("hill_climb+beam")


# ---------------------------------------------------------------------------
# run_week integration
# ---------------------------------------------------------------------------
def test_run_week_uses_optimizer_and_records_strategy():
    members = _roster(50, seed=17)
    wk = trials.run_week(members, skills=SKILLS, strategy="marginal_greedy+hill_climb")
    assert wk.strategy == "marginal_greedy+hill_climb"

    rnd = trials.run_week(members, skills=SKILLS, strategy="random")
    assert rnd.strategy == "random"
    # The optimizer should not do worse than a random draw on the same roster.
    assert wk.total_points >= rnd.total_points
