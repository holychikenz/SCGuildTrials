"""Offline action-level simulation of one trial, to audit the risk model.

DEV-ONLY, and deliberately INDEPENDENT of :mod:`src.calibrate`. Nothing here
calls ``calibrate``'s race, its Wald variance formula, or its Gaussian sampler —
the point is to roll every die individually and see whether the analytic model
told the truth. The only shared code is ``trials`` itself (the party's rates),
which is the *input* both approaches agree on; what is under test is everything
downstream of it.

WHAT IT SIMULATES
-----------------
The real thing, as we understand it:

  * every member acts on their OWN clock, once per ``action_seconds``;
  * each action rolls a success (Bernoulli ``p``) and, on gathering skills, a
    doubling (Bernoulli ``delta``), paying ``floor(work_power) * S * (1 + D)``;
  * work accrues into the current tier's target; when the target is met the party
    advances, the SURPLUS CARRIES OVER (matching ``simulate_race``, whose
    per-tier ``target / rate`` times sum to total-work / rate), and the success
    rate ``p`` drops because the next tier is harder;
  * the clock runs on regardless of tier boundaries — members do not pause.

SYSTEMATICS ARE DELIBERATELY OFF. This run isolates the ALEATORIC term: the
recorded roster, taken at face value, with nothing random but the dice. That
makes the coverage test sharp — see below.

THE COVERAGE TEST, AND WHAT "CORRECT" MEANS HERE
-------------------------------------------------
The shipped bridge claims ``P(tier holds) = Phi(-ln(1 - m) / sigma)``. This
script checks that claim two ways:

  1. against the DICE-ONLY sigma — the model and the simulation then describe the
     same universe, so the curves should lie on top of each other. Any gap is a
     defect in the bridge (wrong distributional family, tier coupling, CLT not
     yet bitten).
  2. against the PUBLISHED sigma, which also carries systematics the simulation
     does not roll. That model is describing a *wider* universe than the one
     being sampled, so it MUST over-cover: its predicted probabilities should sit
     below the empirical ones in the tail. Over-coverage is the desired result —
     it is what makes the published number a conservative floor rather than a
     forecast. Under-coverage here would be a genuine problem.

VECTORISATION
-------------
Runs are simulated in lockstep on a shared time grid: within a step each member
performs a fixed number of actions, so successes are drawn as ONE binomial per
(run, member) rather than one Bernoulli per action — exact, not an approximation,
and about four orders of magnitude faster than rolling individually. Crossing
times are linearly interpolated inside the step so the grid does not quantise the
answer.

USAGE
-----
    python -m src.simulate_trial                      # Foraging, 10000 runs
    python -m src.simulate_trial --skill Milking --runs 20000
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np

from . import config, trials
from .reader import MemberRow

# --- Validated palette (dataviz six-checks, light surface #fcfcfb) ----------
# node scripts/validate_palette.js "#3B6FD4,#C8791A,#B03030" --mode light
#   lightness band PASS · chroma floor PASS · CVD separation PASS (worst
#   adjacent dE 14.6 deutan) · normal-vision floor PASS · contrast PASS
BLUE = "#3B6FD4"    # empirical / simulated
AMBER = "#C8791A"   # analytic model
RED = "#B03030"     # the 3600s buzzer — a threshold, not a series
INK = "#1c1c1c"
MUTED = "#6b6b6b"
GRID = "#e3e3e0"
SURFACE = "#fcfcfb"


# ---------------------------------------------------------------------------
# Party assembly
# ---------------------------------------------------------------------------
@dataclass
class Party:
    """The prepared, UNPERTURBED party — recorded sheet values, nothing random."""

    skill: str
    n: int                 # headcount, which sets the (1 + N/100) work target
    work: np.ndarray       # floor(work_power) per member
    asec: np.ndarray       # action_seconds per member
    p: np.ndarray          # success rate, shape (tier, member)
    delta: float           # doubling chance (gathering only)
    max_tier: int

    def targets(self) -> np.ndarray:
        """``effective_target(t, N)`` for t = 1..max_tier."""
        return np.array([
            trials.effective_target(t, self.n, config.TARGET_SCALE)
            for t in range(1, self.max_tier + 1)
        ])


def build_party(members: list[MemberRow], skill: str, max_tier: int = 16) -> Party:
    """Prepare the party exactly as ``simulate_race`` does, then expose the parts.

    Uses ``trials._prepare_member`` so the per-member factors are the SAME ones
    the shipped model races with — the input is not what is being audited.
    """
    bl = trials.guild_building_skill_levels(skill)
    prep = [p for p in (trials._prepare_member(m, skill, bl) for m in members)
            if p is not None]
    work = np.array([wp for _, _, _, _, wp, _ in prep], dtype=np.float64)
    asec = np.array([a for _, _, _, _, _, a in prep], dtype=np.float64)
    double = prep[0][3]
    p = np.array([
        [trials.success(lv, t, sb, b) for lv, sb, b, _, _, _ in prep]
        for t in range(1, max_tier + 1)
    ])
    return Party(skill=skill, n=len(members), work=work, asec=asec, p=p,
                 delta=double - 1.0, max_tier=max_tier)


# ---------------------------------------------------------------------------
# The simulation
# ---------------------------------------------------------------------------
def simulate(
    party: Party,
    runs: int = 10000,
    dt: float = 10.0,
    horizon: float = 6000.0,
    seed: int = 20260801,
    carryover: bool = True,
) -> np.ndarray:
    """Roll ``runs`` independent trials; return clear times, shape (runs, tiers).

    ``NaN`` where a run never reached that tier inside ``horizon``. Tier index i
    holds the clock reading at which tier ``i + 1`` was banked.

    ``carryover`` decides what happens to the SURPLUS work earned in the instant a
    tier is banked, and it is not a detail — it is an open question about the game
    that the shipped model answers implicitly.

      * ``False`` (diagnostic only): the accumulator resets at every boundary, so
        each tier needs its own ``TotalWork`` from scratch. This LOOKS like the
        literal reading of ``simulate_race`` (whose per-tier ``target / rate``
        times simply sum) but it is not equivalent under discretisation — see the
        grid-bias table below — and it should not be used for a headline number.
      * ``True`` (the default, and the physically faithful one): surplus rolls
        into the next tier, as it must if work accrues continuously and members do
        not pause at a boundary.

    GRID BIAS — READ BEFORE TRUSTING A MEAN. Both variants carry an O(dt)
    discretisation bias, in OPPOSITE directions, because a threshold is only
    detected at a step boundary:

        dt (s)    carryover=True    carryover=False     deterministic
          20          3508.1            3652.2              3534.9
          10          3522.0            3594.0              3534.9
           4          3531.3            3563.9              3534.9
           2          3532.5              —                 3534.9

    Resetting the accumulator DISCARDS on average half a step of work, which is
    why ``carryover=False`` runs slow and does so in proportion to dt. Carrying it
    over converges on the deterministic answer instead — which is the substantive
    result: ``simulate_race`` is UNBIASED, and an apparent 13s of free margin at
    dt=10 was an artefact of the grid, not a property of the game. Keep dt small
    (<= 2s) for any statement about the mean; sigma is far less sensitive (it
    varies by under 2% across the whole table above).
    """
    rng = np.random.default_rng(seed)
    targets = party.targets()
    n_tiers = party.max_tier
    n_mem = party.work.size

    steps = int(math.ceil(horizon / dt))
    # Actions completed by each member at every grid boundary. The member's clock
    # runs continuously across tier boundaries — they do not pause to celebrate.
    edges = np.arange(steps + 1) * dt
    done = np.floor(edges[:, None] / party.asec[None, :]).astype(np.int64)
    per_step = np.diff(done, axis=0)          # (steps, members)

    tier = np.zeros(runs, dtype=np.int64)     # 0-based index of the tier in progress
    accum = np.zeros(runs)
    out = np.full((runs, n_tiers), np.nan)
    alive = np.ones(runs, dtype=bool)

    for g in range(steps):
        if not alive.any():
            break
        n_act = per_step[g]                                   # (members,)
        if n_act.sum() == 0:
            continue
        idx = np.minimum(tier, n_tiers - 1)
        p_now = party.p[idx]                                  # (runs, members)
        n_b = np.broadcast_to(n_act, (runs, n_mem))
        succ = rng.binomial(n_b, p_now)
        if party.delta > 0:
            succ = succ + rng.binomial(succ, party.delta)
        gained = (succ * party.work).sum(axis=1)              # (runs,)

        # A step may carry a run across MORE than one tier when the tiers are
        # short (they are, early on), so drain in a loop rather than assuming one.
        # ``spent`` tracks the fraction of THIS step's work already consumed, so a
        # second crossing inside the same step is timed from where the first left
        # off rather than from the step boundary.
        accum = accum + gained
        spent = np.zeros(runs)
        for _ in range(n_tiers):
            cur = np.minimum(tier, n_tiers - 1)
            hit = alive & (tier < n_tiers) & (accum >= targets[cur])
            if not hit.any():
                break
            need = targets[tier[hit]]
            over = accum[hit] - need          # work earned AFTER the threshold
            # Linear interpolation inside the step: work accrues steadily within
            # dt, so the crossing sits where the remaining shortfall runs out.
            used = np.where(gained[hit] > 0, 1.0 - over / gained[hit], 1.0)
            used = np.clip(used, spent[hit], 1.0)
            out[hit, tier[hit]] = edges[g] + dt * used
            spent[hit] = used
            # Reset (default) or carry the surplus — see the docstring.
            accum[hit] = over if carryover else 0.0
            tier[hit] += 1
            alive = alive & (tier < n_tiers)
    return out


# ---------------------------------------------------------------------------
# The analytic model being audited
# ---------------------------------------------------------------------------
def phi(z: np.ndarray | float) -> np.ndarray | float:
    from scipy.special import ndtr
    return ndtr(z)


def analytic(party: Party) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic clearing times and the Wald dice-only sigma, per tier.

    Re-derived here rather than imported, so the audit does not lean on the code
    it is auditing. ``sigma_t`` is the sd of ``ln tau_t``, accumulated in
    quadrature over the tiers raced so far.
    """
    targets = party.targets()
    taus, sds = [], []
    cum_t, cum_var = 0.0, 0.0
    for i in range(party.max_tier):
        p = party.p[i]
        rate = (p * (1 + party.delta) * party.work / party.asec).sum()
        # Var[X] = W^2 [ p(1+3d) - p^2 (1+d)^2 ]  per action; /a gives a rate.
        vrate = (party.work ** 2
                 * (p * (1 + 3 * party.delta) - p ** 2 * (1 + party.delta) ** 2)
                 / party.asec).sum()
        cum_t += targets[i] / rate
        cum_var += targets[i] * vrate / rate ** 3     # Wald first-passage variance
        taus.append(cum_t)
        sds.append(math.sqrt(cum_var) / cum_t)        # -> sd of ln tau
    return np.array(taus), np.array(sds)


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------
def _style(ax):
    ax.set_facecolor(SURFACE)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=3)
    ax.grid(True, color=GRID, linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for lbl in (ax.xaxis.label, ax.yaxis.label):
        lbl.set_color(MUTED)
        lbl.set_fontsize(10)


def plot_histogram(tau: np.ndarray, tier: int, tau_det: float, sigma: float,
                   budget: float, path: str, skill: str) -> float:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ok = np.isfinite(tau)
    tau = tau[ok]
    p_emp = float((tau <= budget).mean())
    p_mod = float(phi(math.log(budget / tau_det) / sigma))

    fig, ax = plt.subplots(figsize=(9, 5.2), facecolor=SURFACE)
    _style(ax)
    lo, hi = np.percentile(tau, [0.05, 99.95])
    # 48 bins, not 70: members act on a discrete lattice (k * action_seconds), so
    # clear times inherit a fine comb. Narrow bins resolve the comb and it reads
    # as noise in the data rather than what it is — an artefact of the encoding.
    bins = np.linspace(min(lo, budget * 0.985), max(hi, budget * 1.01), 48)
    ax.hist(tau, bins=bins, color=BLUE, alpha=0.85, edgecolor=SURFACE, linewidth=0.6,
            label=f"simulated ({len(tau):,} runs, dice only)")

    # The analytic log-normal, scaled to the histogram's area — the claim on trial.
    xs = np.linspace(bins[0], bins[-1], 600)
    pdf = (np.exp(-((np.log(xs / tau_det)) ** 2) / (2 * sigma ** 2))
           / (xs * sigma * math.sqrt(2 * math.pi)))
    ax.plot(xs, pdf * len(tau) * (bins[1] - bins[0]), color=AMBER, linewidth=2.0,
            label=f"analytic log-normal (σ = {sigma:.4f})")

    ax.axvline(budget, color=RED, linewidth=2.0)
    ax.axvspan(budget, bins[-1], color=RED, alpha=0.07, linewidth=0)
    ymax = ax.get_ylim()[1]
    ax.annotate(f"{budget:.0f}s buzzer", xy=(budget, ymax * 0.97),
                xytext=(6, 0), textcoords="offset points", color=RED,
                fontsize=10, fontweight="bold", va="top")
    ax.annotate(f"tier {tier} HELD\n{p_emp:.1%} of runs",
                xy=(budget * 0.9955, ymax * 0.60), color=INK, fontsize=11,
                ha="right", fontweight="bold")
    ax.annotate(f"tier {tier} LOST\n{1 - p_emp:.1%}",
                xy=(budget * 1.0018, ymax * 0.60), color=RED, fontsize=11,
                ha="left", fontweight="bold")

    ax.set_xlabel(f"clock reading when tier {tier} is banked  (seconds)")
    ax.set_ylabel("runs")
    ax.set_title(f"{skill} — when the party banks tier {tier}",
                 color=INK, fontsize=13, fontweight="bold", loc="left", pad=30)
    ax.text(0, 1.035, f"model predicts {p_mod:.1%} · simulation says {p_emp:.1%}",
            transform=ax.transAxes, color=MUTED, fontsize=10)
    leg = ax.legend(frameon=False, fontsize=9.5, loc="upper left")
    for t in leg.get_texts():
        t.set_color(MUTED)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return p_emp


def plot_coverage(tau: np.ndarray, tau_det: float, sigma_dice: float,
                  sigma_pub: float, path: str, skill: str, tier: int) -> None:
    """Predicted vs realised probability across a sweep of hypothetical deadlines.

    A deadline sweep rather than a single point, because one number cannot
    distinguish "right on average" from "right everywhere". The 45-degree line is
    perfect calibration; ABOVE it means the model under-promises (over-covers).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tau = tau[np.isfinite(tau)]
    deadlines = np.percentile(tau, np.linspace(0.5, 99.5, 240))
    emp = np.array([(tau <= b).mean() for b in deadlines])
    mod_dice = phi(np.log(deadlines / tau_det) / sigma_dice)
    mod_pub = phi(np.log(deadlines / tau_det) / sigma_pub)

    fig, ax = plt.subplots(figsize=(7.4, 6.4), facecolor=SURFACE)
    _style(ax)
    ax.plot([0, 1], [0, 1], color=MUTED, linewidth=1.2, linestyle=(0, (4, 3)),
            label="perfect calibration")
    ax.plot(mod_dice, emp, color=BLUE, linewidth=2.4,
            label=f"dice-only model (σ = {sigma_dice:.4f})")
    ax.plot(mod_pub, emp, color=AMBER, linewidth=2.4,
            label=f"published model (σ = {sigma_pub:.4f}, incl. systematics)")

    ax.fill_between([0, 1], [0, 1], [1, 1], color=BLUE, alpha=0.05, linewidth=0)
    ax.annotate("model under-promises\n(conservative — desired)", xy=(0.28, 0.86),
                color=MUTED, fontsize=9.5, ha="center")
    ax.annotate("model over-promises\n(dangerous)", xy=(0.80, 0.42),
                color=RED, fontsize=9.5, ha="center")

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.set_xlabel("probability the model predicts")
    ax.set_ylabel("proportion of runs that actually cleared")
    ax.set_title(f"{skill} tier {tier} — does the bridge tell the truth?",
                 color=INK, fontsize=13, fontweight="bold", loc="left", pad=14)
    leg = ax.legend(frameon=False, fontsize=9.5, loc="lower right")
    for t in leg.get_texts():
        t.set_color(MUTED)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def plot_sigma_by_tier(sim: np.ndarray, taus: np.ndarray, sds: np.ndarray,
                       path: str, skill: str, top: int) -> None:
    """Simulated sd(ln tau) against the Wald prediction, tier by tier."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tiers, emp = [], []
    for i in range(sim.shape[1]):
        col = sim[:, i]
        col = col[np.isfinite(col)]
        if col.size > 500:
            tiers.append(i + 1)
            emp.append(np.log(col).std(ddof=1))
    fig, ax = plt.subplots(figsize=(9, 4.8), facecolor=SURFACE)
    _style(ax)
    ax.plot(tiers, emp, color=BLUE, linewidth=2.2, marker="o", markersize=6,
            markeredgecolor=SURFACE, markeredgewidth=1.5, label="simulated (rolled)")
    ax.plot(tiers, sds[:len(tiers)], color=AMBER, linewidth=2.2, marker="s",
            markersize=5.5, markeredgecolor=SURFACE, markeredgewidth=1.5,
            label="analytic (Wald first passage)")
    ax.axvline(top, color=RED, linewidth=1.6, linestyle=(0, (3, 3)))
    lo, hi = ax.get_ylim()
    ax.annotate(f"tier reached ({top})", xy=(top, lo + (hi - lo) * 0.06),
                xytext=(-8, 0), textcoords="offset points", color=RED, fontsize=9.5,
                ha="right")
    ax.set_xlabel("tier")
    ax.set_ylabel("sd of ln(clear time)")
    # The shape is a U, and naming it is the whole point of the chart: few actions
    # early (relative noise high), then the CLT bites, then the success rate
    # collapses toward SUCCESS_FLOOR and per-action variance climbs again.
    ax.set_title(f"{skill} — aleatoric σ by tier",
                 color=INK, fontsize=13, fontweight="bold", loc="left", pad=30)
    ax.text(0, 1.035,
            "falls as actions accumulate, then climbs as success rates collapse "
            "toward the 5% floor",
            transform=ax.transAxes, color=MUTED, fontsize=10)
    leg = ax.legend(frameon=False, fontsize=9.5, loc="upper center")
    for t in leg.get_texts():
        t.set_color(MUTED)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skill", default="Foraging")
    ap.add_argument("--runs", type=int, default=10000)
    ap.add_argument("--dt", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=20260801)
    ap.add_argument("--guild", default="sc", choices=sorted(config.TABS))
    ap.add_argument("--sigma-published", type=float, default=0.0231,
                    help="sigma incl. systematics, from the calibration campaign")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--no-carryover", dest="carryover", action="store_false",
                    help="discard surplus work at a tier boundary (grid-biased "
                         "slow; see simulate() -- for diagnosis only)")
    args = ap.parse_args(argv)

    root = os.path.dirname(os.path.dirname(__file__))
    outdir = args.outdir or os.path.join(root, "research", "figures")
    os.makedirs(outdir, exist_ok=True)
    signup = os.path.join(root, "_site" if args.guild == "sc"
                          else os.path.join("_site", args.guild), "signup.json")

    from .scraper import scrape_member_tab
    data = scrape_member_tab(config.TABS[args.guild])
    with open(signup) as fh:
        plan = json.load(fh)
    by_name = {m.name: m for m in data.members}
    entry = next(t for t in plan["trials"] if t["skill"] == args.skill)
    party_rows = [by_name[r["name"]] for r in entry["roster"]]

    party = build_party(party_rows, args.skill)
    taus_det, sds = analytic(party)

    ref = trials.simulate_race(party_rows, args.skill)
    top = ref.tier_reached
    budget = config.TRIAL_TIME_BUDGET_SECONDS

    # Cross-check the re-derived deterministic times against the shipped model
    # before trusting anything else in this file.
    worst = max(
        abs(taus_det[s.tier - 1] - s.cumulative_time) / s.cumulative_time
        for s in ref.timeline if s.cumulative_time is not None
    )
    print(f"party: {args.skill}, N={party.n}, tier reached {top}")
    print(f"deterministic tau_{top} = {taus_det[top - 1]:.1f}s  "
          f"(margin {1 - taus_det[top - 1] / budget:.2%})")
    print(f"re-derivation vs simulate_race: max relative deviation {worst:.2e}")
    assert worst < 1e-9, worst

    print(f"\nrolling {args.runs:,} runs at dt={args.dt}s ...")
    sim = simulate(party, runs=args.runs, dt=args.dt, seed=args.seed,
                   carryover=args.carryover)

    col = sim[:, top - 1]
    finite = np.isfinite(col)
    s_emp = float(np.log(col[finite]).std(ddof=1))
    s_ana = float(sds[top - 1])
    print(f"\nsigma at tier {top}:  simulated {s_emp:.5f}   analytic(Wald) {s_ana:.5f}"
          f"   ratio {s_emp / s_ana:.4f}")
    print(f"mean tau: simulated {col[finite].mean():.1f}s  "
          f"deterministic {taus_det[top - 1]:.1f}s")

    h = os.path.join(outdir, f"{args.skill.lower()}_clear_time.png")
    p_emp = plot_histogram(col, top, taus_det[top - 1], s_ana, budget, h, args.skill)
    c = os.path.join(outdir, f"{args.skill.lower()}_coverage.png")
    plot_coverage(col, taus_det[top - 1], s_ana, args.sigma_published, c,
                  args.skill, top)
    s = os.path.join(outdir, f"{args.skill.lower()}_sigma_by_tier.png")
    plot_sigma_by_tier(sim, taus_det, sds, s, args.skill, top)

    p_dice = float(phi(math.log(budget / taus_det[top - 1]) / s_ana))
    p_pub = float(phi(math.log(budget / taus_det[top - 1]) / args.sigma_published))
    print(f"\nP(tier {top} holds):")
    print(f"   simulated (truth)            {p_emp:.4f}")
    print(f"   model, dice-only sigma       {p_dice:.4f}   "
          f"error {p_dice - p_emp:+.4f}")
    print(f"   model, published sigma       {p_pub:.4f}   "
          f"error {p_pub - p_emp:+.4f}  "
          f"({'OVER-covers (conservative)' if p_pub < p_emp else 'UNDER-covers'})")

    # Integrated coverage error across the whole sweep, not just the buzzer.
    t = col[finite]
    deadlines = np.percentile(t, np.linspace(0.5, 99.5, 400))
    emp = np.array([(t <= b).mean() for b in deadlines])
    for label, sg in (("dice-only", s_ana), ("published", args.sigma_published)):
        mod = np.asarray(phi(np.log(deadlines / taus_det[top - 1]) / sg))
        print(f"   coverage sweep [{label:>10}]  mean |error| {np.abs(mod - emp).mean():.4f}"
              f"   max |error| {np.abs(mod - emp).max():.4f}"
              f"   mean signed {np.mean(mod - emp):+.4f}")

    print(f"\nfigures written to {outdir}/")
    for f in (h, c, s):
        print("   " + os.path.relpath(f, root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
