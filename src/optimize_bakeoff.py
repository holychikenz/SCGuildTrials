"""Bake-off harness: compare optimizer strategies on points AND speed.

Runnable: ``python -m src.optimize_bakeoff [--live] [--seeds N] [--csv]``

Each strategy is run against the same roster(s) and the same per-strategy seed
sequence, and judged on:

  * **points**  — total guild points (mean and worst-case across seeds); PRIMARY
  * **time_ms** — wall-clock per run (mean)
  * **sims**    — genuine simulate_race calls (cache misses); the oracle-call
                  "how quickly" axis, free of wall-clock noise

Rosters: synthetic by default (varied size/level spread, to stress the headcount
trade-off) and — with ``--live`` — the real SURVEY CORPS member sheet. A ninth
contestant, ``scipy_lap`` (linear-assignment on the rate proxy), is included ONLY
if SciPy is installed (a ``[dev]`` extra); it is soft-imported and skipped
otherwise, so this harness never puts SciPy on the CI build path.

This module is a benchmark/dev tool: it is NOT imported by ``src.build`` and adds
no dependency to the shipped pipeline.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Optional

from . import config
from .optimizer import AssignmentScorer, optimize, run_strategy
from .reader import MemberRow, SkillEntry

# Strategy field for the bake-off. Constructors alone, plus constructor+refiner
# pairings, so the table shows both raw seeds and what refinement buys.
STRATEGIES = [
    "random",
    "proxy_greedy",
    "marginal_greedy",
    "beam",
    "genetic",
    "proxy_greedy+hill_climb",
    "proxy_greedy+sa",
    "proxy_greedy+sa+hill_climb",
    "marginal_greedy+hill_climb",
    "marginal_greedy+sa+hill_climb",
    "beam+hill_climb",
    "beam+genetic",
    "beam+genetic+hill_climb",
    "genetic+hill_climb",
    "best",  # the shipped ensemble default
]

# SciPy linear-assignment contestant (dev-only, soft import — see module docs).
try:  # pragma: no cover - availability depends on the [dev] extra
    from scipy.optimize import linear_sum_assignment as _lsa  # noqa: F401

    _HAS_SCIPY = True
except Exception:  # pragma: no cover
    _HAS_SCIPY = False


# ---------------------------------------------------------------------------
# Rosters
# ---------------------------------------------------------------------------
def _synthetic_roster(
    n: int, seed: int, skills: list[str]
) -> list[MemberRow]:
    """Build ``n`` synthetic members with a varied level spread per skill.

    Deterministic given ``seed``. Levels span a wide band (including some below
    the tier-1 level of 100, i.e. genuine stragglers) so the headcount trade-off
    is actually exercised. Tool/top/bot checkboxes are randomly set.
    """
    rng = random.Random(seed)
    sheet_cols = config.SKILLS
    members: list[MemberRow] = []
    for i in range(n):
        entries: dict[str, SkillEntry] = {}
        for col in sheet_cols:
            # A member is "specialised": strong in a random subset of skills,
            # mediocre-to-weak elsewhere.
            if rng.random() < 0.4:
                level = rng.randint(110, 145)
            else:
                level = rng.randint(70, 115)
            entries[col] = SkillEntry(
                level=level,
                tool=rng.random() < 0.5,
                top=rng.random() < 0.4,
                bot=rng.random() < 0.4,
            )
        members.append(
            MemberRow(
                name=f"syn{i:03d}",
                main_classes="",
                flex="",
                flex_levels=[],
                skills=entries,
            )
        )
    return members


def _live_roster() -> Optional[list[MemberRow]]:
    """Fetch the live SC member roster; returns None on any network failure."""
    try:
        from .scraper import scrape_member_tab

        return scrape_member_tab(config.TABS["sc"]).members
    except Exception as exc:  # network / structure — degrade gracefully
        print(f"  (live roster unavailable: {exc})", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# SciPy linear-assignment contestant (dev-only)
# ---------------------------------------------------------------------------
def _scipy_lap_parties(
    scorer: AssignmentScorer, seed: int
) -> list[set]:  # pragma: no cover - exercised only with scipy installed
    """Linear-assignment on the rate proxy: classic solver as a benchmark seed.

    Each skill is expanded into ``cap`` identical columns (so up to ``cap``
    members can share a slot), plus a block of bench columns. Cost = negative
    proxy rate. This ignores the headcount penalty and the step objective by
    construction — its whole point is to measure how much that costs versus the
    true-objective strategies.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    from .optimizer import _rate_matrix

    n = len(scorer.members)
    S = len(scorer.skills)
    cap = scorer.cap
    rm = _rate_matrix(scorer.members, scorer.skills)

    slot_cols = S * cap
    total_cols = slot_cols + n  # n bench columns guarantee a feasible matching
    cost = np.zeros((n, total_cols), dtype=float)
    for m in range(n):
        for s in range(S):
            for c in range(cap):
                cost[m, s * cap + c] = -rm[m][s]
        # bench columns: cost 0 (worse than any positive rate)
    rows, cols = linear_sum_assignment(cost)
    parties: list[set] = [set() for _ in range(S)]
    for m, col in zip(rows, cols):
        if col < slot_cols:
            s = col // cap
            if rm[m][s] > 0:  # never assign a zero/negative-rate member
                parties[s].add(m)
    return parties


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------
@dataclass
class Row:
    strategy: str
    mean_points: float
    min_points: int
    mean_ms: float
    mean_sims: float


def _run_one(
    members: list[MemberRow],
    skills: list[str],
    strategy: str,
    seed: int,
) -> tuple[int, float, int]:
    """Run one strategy once; return (points, elapsed_ms, sim_calls)."""
    scorer = AssignmentScorer(
        members, skills, config.TARGET_SCALE, config.TRIAL_PARTY_CAP
    )
    t0 = time.perf_counter()
    if strategy == "scipy_lap":  # pragma: no cover
        parties = _scipy_lap_parties(scorer, seed)
    else:
        parties = run_strategy(scorer, strategy, seed)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    points = scorer.total_points(parties)
    return points, elapsed_ms, scorer.sim_calls


def bake_off(
    members: list[MemberRow],
    skills: list[str],
    seeds: list[int],
    strategies: list[str],
) -> list[Row]:
    """Run every strategy over every seed; return aggregated rows (best first)."""
    rows: list[Row] = []
    for strat in strategies:
        pts: list[int] = []
        ms: list[float] = []
        sims: list[int] = []
        for sd in seeds:
            p, t, s = _run_one(members, skills, strat, sd)
            pts.append(p)
            ms.append(t)
            sims.append(s)
        rows.append(
            Row(
                strategy=strat,
                mean_points=statistics.mean(pts),
                min_points=min(pts),
                mean_ms=statistics.mean(ms),
                mean_sims=statistics.mean(sims),
            )
        )
    rows.sort(key=lambda r: (-r.mean_points, r.mean_ms))
    return rows


def _print_table(title: str, rows: list[Row]) -> None:
    print(f"\n=== {title} ===")
    print(
        f"{'strategy':<28} {'mean_pts':>9} {'min_pts':>8} "
        f"{'mean_ms':>9} {'mean_sims':>10}"
    )
    print("-" * 68)
    for r in rows:
        print(
            f"{r.strategy:<28} {r.mean_points:>9.1f} {r.min_points:>8d} "
            f"{r.mean_ms:>9.1f} {r.mean_sims:>10.0f}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Optimizer bake-off")
    parser.add_argument(
        "--live", action="store_true", help="also benchmark the live SC roster"
    )
    parser.add_argument(
        "--seeds", type=int, default=5, help="number of seeds per strategy"
    )
    parser.add_argument(
        "--sizes",
        type=str,
        default="40,86,120",
        help="comma-separated synthetic roster sizes",
    )
    args = parser.parse_args(argv)

    skills = list(config.TRIAL_SKILLS_CURRENT)
    seeds = list(range(1, args.seeds + 1))
    strategies = list(STRATEGIES)
    if _HAS_SCIPY:
        strategies.append("scipy_lap")
    else:
        print("(scipy not installed — skipping scipy_lap contestant)")

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    for n in sizes:
        roster = _synthetic_roster(n, seed=1000 + n, skills=skills)
        rows = bake_off(roster, skills, seeds, strategies)
        _print_table(f"synthetic roster n={n} ({args.seeds} seeds)", rows)

    if args.live:
        roster = _live_roster()
        if roster:
            rows = bake_off(roster, skills, seeds, strategies)
            _print_table(f"LIVE SC roster n={len(roster)}", rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
