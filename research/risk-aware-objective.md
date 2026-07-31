# Risk-aware trial objective: breaking the degeneracy of the Asimov cost function

**Status**: §1–§2 are measurements, and they are the reason the shipped change
exists. **What actually shipped is only Model 1 of §4** — `optimizer._refine_slack`,
a single points-preserving post-search pass maximising
`(total_points, min_margin, sum_margin)`. Models 2–6 and routines R1/R3–R7 are
**not implemented**, and are recorded here as the map for later, should the margin
ever need to become a probability. Do not read §4–§6 as describing the code.

**Shipped result** (live rosters, 2026-07-31, shipped budget): the minimum margin
across the four trials rose from **4.28% to 17.92%** on Survey Corps and from
**0.26% (9.3 seconds) to 16.41%** on Lactose lntolerance, at **zero** change in
guild points, for +40% on the optimize step.
**Scope**: `src/trials.py` (`simulate_race`), `src/optimizer.py`
(`AssignmentScorer`), `src/config.py`, `src/optimize_bakeoff.py`, and the
presentation in `src/build.py` / `src/signup.py`.
**Measurements**: taken 2026-07-31 on the LIVE Survey Corps roster (96 members),
draw `[Milking, Foraging, Crafting, Alchemy]`, strategy
`beam+genetic+hill_climb` @ seed 1235, `OPT_*` budgets reduced for probe speed.

---

## 1. The diagnosis

`simulate_race` is evaluated on the **Asimov dataset**: every stochastic quantity
is replaced by its expectation. `success` returns a *probability* and is used as
though it were a *yield*; `double_chance` returns a *chance* and is used as a
multiplier. The race is therefore a single deterministic trajectory, the tier
reached is an integer, and

```python
scorer.party_points(...)  ->  points_for_tier(tier_reached)  ->  int
```

is a **step function of a deterministic quantity**. Two consequences:

1. **The optimizer is blind to margin.** A party that clears tier 11 with 100
   seconds to spare and one that clears it with 900 seconds to spare are the same
   1200 points. The search has no gradient on the plateau — a fact the code
   already half-knows: `_construct_marginal_greedy` has a whole paragraph
   explaining that it must walk *through* gain-0 placements because "several
   members must join before a tier threshold is crossed".
2. **The reported score is biased upward.** The tier that the expected trajectory
   *just* clears is not the tier the guild will *usually* reach.

### 1.1 The degeneracy is real, and it is expensive

Measured on the incumbent 4900-point solution: 25 distinct assignments, all
scoring **exactly 4900** deterministic points, sampled from single- to
triple-move neighbourhoods.

| quantity | min | max | spread |
|---|---|---|---|
| total time slack (fraction of budget, summed over 4 trials) | 0.320 | 0.380 | 0.060 |
| **E[points]** under the risk model of §3 | **4771.9** | **4826.7** | **54.7** |

Standard deviation across the 25: 10.2 points. **The spread is over half a tier**,
and these are only *local* neighbours — the plateau reachable by the ensemble's
four restarts is wider still. The incumbent happens to land near the top (4822.3)
by luck, not by design; nothing in the search is pulling it there.

### 1.2 The slack it is throwing away is already computed

`TrialResult.timeline` carries `cumulative_time` for every tier, including the
first failed one. The information needed for every model below is *already in the
return value* and is being discarded by `.points`.

| trial | tier | τ_T (s) | slack (s) | slack % of budget |
|---|---|---|---|---|
| Milking | 12 | 3136.5 | 463.5 | 12.9% |
| Foraging | 12 | 3353.7 | 246.3 | 6.8% |
| Crafting | 11 | 3499.9 | 100.1 | **2.8%** |
| Alchemy | 10 | 3042.0 | 558.0 | 15.5% |

Crafting is holding its 1200th point by 100 seconds in 3600. That is not a tier;
that is a coin-flip wearing a tier's clothing.

---

## 2. Where the variance actually lives

Three families, with very different mathematics and very different magnitudes.
Getting the *taxonomy* right matters more than getting any single σ right,
because the families scale differently with party size.

### (A) Diffusive — per-action, aleatoric, exactly derivable

Each action is Bernoulli. Progress per action for member *m* at tier *t*:

```
X = W · S · (1 + D),      S ~ Bern(p),  D ~ Bern(δ),  independent
```

with `W = floor(work_power)`, `p = success(...)`, `δ = double_chance(skill)`.

```
E[X]   = W · p · (1 + δ)                        (= the current model, exactly)
E[X²]  = W² · p · (1 + 3δ)                      since E[(1+D)²] = 1 + 3δ
Var[X] = W² · [ p(1 + 3δ) − p²(1 + δ)² ]        (→ W²p(1−p) when δ = 0 ✓)
```

**Action *count* is deterministic** (`action_seconds` is fixed), so a member
performs exactly `τ/a_m` actions in time τ and only the *payload* is random.
That is the ideal setting for the CLT. Party work accumulates with

```
drift          R_t = Σ_m  p_m(t) · (1+δ) · W_m / a_m        (unchanged)
variance rate  V_t = Σ_m  W_m² [ p_m(1+3δ) − p_m²(1+δ)² ] / a_m
```

First-passage time to a work level Y under drift R and variance rate V is
inverse-Gaussian with mean `Y/R` and variance `Y·V/R³` (standard Wald result).
Phases (tiers) are sequential and, to first order, independent, so

```
σ²_diff(t) = Σ_{u ≤ t}  Target(u,N) · V_u / R_u³
```

*Assumption (flag it):* **efficiency contributes no variance.** The capture in
`research/trial-messages.md` shows `progressPerAction: 133` alongside
`efficiency: 0.317` and level ≈ 101, i.e. the engine has already folded
efficiency deterministically into the per-action payload — exactly as
`work_power` does. If a later capture shows efficiency behaving as an
instant-repeat *chance*, a compound-Poisson term must be added to `Var[X]`.

**Measured** σ_diff at the marginal tier: **44–62 s**. Against slacks of 100–558 s
that is z ≈ 1.9 (Crafting) to 12.6 (Alchemy). Not negligible — but see (B).

### (B) Persistent multiplicative — turnout and model error

Everything that perturbs the party rate *for the whole hour* rather than
per-action:

- **turnout** — an assigned member does not show, or spends their 2 h weekly
  budget elsewhere;
- **stale sheet levels**, blank `H` cells defaulting to 4, unmodelled achievement
  bonuses;
- **community buffs expiring** mid-week (`COMMUNITY_*` are all flagged working
  assumptions);
- **the model constants themselves** — `TIER_TARGET_PER_LEVEL = 400`,
  `TARGET_SCALE`, the `(1 + N/100)` vs `1.01^N` reading, `points_for_tier`.

These act as a **common shock** on R. They do **not** average down with party
size or with time. Write `R̃ = R·e^ε`, `ε ~ N(0, σ_ε²)`; then the clearing time
is `τ_t·e^{−ε}` and everything below follows from τ alone.

**Measured** σ_pers at the marginal tier (dropout q=0.9 ⊕ σ_param=0.08):
**352–389 s** — roughly **7× the diffusive term**. In quadrature the diffusive
part contributes ~1% of σ_total. *The persistent family is the whole story.*

### (C) Structural — composition risk

Within the dropout part of (B), the discriminating statistic is the
**participation ratio** (inverse Herfindahl / effective number of contributors):

```
k_eff(t) = R_t² / Σ_m r_m(t)²          →     CV_drop(t) ≈ √( (1−q)/q / k_eff(t) )
```

A party whose marginal tier rests on three whales is fragile; one with the same
total rate spread over twenty members is not. **This is the term that makes
*composition* — not just total rate — matter**, and it is the mechanism by which
a risk-aware objective produces *strategically different* advice rather than
merely a different tie-break.

**Measured** k_eff at the marginal tier: 11.4 (Alchemy) to 23.8 (Foraging) out of
N=24. The spread is narrower than one might hope, because the `SUCCESS_FLOOR = 0.05`
equalises contributions once the tier level outruns everybody's skill — but
Alchemy resting on an effective 11 of its 24 members is a genuine, and currently
invisible, exposure.

---

## 3. The unifying reformulation

**Key structural fact: the tier events are nested.** `simulate_race` clears tiers
in order against a cumulative budget, and τ_t is strictly increasing in t. Any
perturbation that raises rates (a common shock, a member showing up, a lucky run
of successes) can only move a tier from *not cleared* to *cleared*. Hence

```
{clear t+1} ⊂ {clear t}
```

which collapses the whole distribution onto a single monotone survival curve:

```
S(t) := P(T ≥ t) = P(τ̃_t ≤ 3600)
P(T = t) = S(t) − S(t+1)
```

and, since `points(T) = 100 + 100·T` for T ≥ 1 and E[T] = Σ_{t≥1} P(T≥t) for a
non-negative integer T:

```
E[points]  =  TRIAL_POINTS_BASE · S(1)  +  TRIAL_POINTS_PER_TIER · Σ_{t ≥ 1} S(t)
```

That is the entire cost function. Everything else is a choice of how to compute
S(t). With a Gaussian approximation:

```
S(t) = Φ(z_t),        z_t = (3600 − τ_t) / σ_t
σ_t² = σ²_diff(t) + (τ_t · CV_t)²
CV_t² = (1−q)/q · Σ_m r_m(t)² / R_t²  +  σ_param²
                └── dropout, needs Σr² ──┘   └─ one constant ─┘
```

**Properties worth having:**

- **Smooth and strictly monotone in slack** — the degeneracy is destroyed by
  construction, and the search gains a gradient on what used to be a plateau.
- **Exact reduction**: as σ → 0, `Φ(z_t) → 1{τ_t ≤ 3600}` and E[points] →
  `points_for_tier(tier_reached)`, *identically*. The new objective contains the
  old one as a limit, which makes the σ→0 test a hard equality assertion.
- **Tier ordering preserved**: a plan that clears a strictly higher tier at equal
  σ always scores higher, so risk-awareness cannot silently trade tiers away
  (and §5 R2/Model 1 make that a *guarantee* rather than a tendency).

Measured on the incumbent: **E = 4822.3** against a deterministic 4900, with tier
distributions `Milking T11:10% T12:89% T13:1%`, `Foraging T11:25% T12:75%`,
`Crafting T10:40% T11:60%`, `Alchemy T9:6% T10:92% T11:2%`. Note the *upside*
terms (T13, T11) — the current objective scores those at zero.

---

## 4. The model menu

Ordered by cost. Costs are measured per `simulate_race` on the live 24-member
Milking party, 13 tiers, 6000 repetitions.

| # | model | extra cost / race | what it buys |
|---|---|---|---|
| 1 | ε-lexicographic slack tie-break | **0%** | breaks degeneracy, provably safe |
| 2 | common-shock survival (deadline shrink) | **0%** | full E[points], correct sign of the bias |
| 3 | + dropout / k_eff aware | **+6.4%** | composition risk; consumes sign-up data |
| 4 | + diffusive (exact aleatoric) | +10–15% (see §4.4) | mathematical completeness (~1% of σ) |
| 5 | quantile / CVaR via scenario quadrature | ~0% on top of 2 | risk-averse objective, correct cross-trial correlation |
| 6 | mean–variance / entropic utility | ~0% on top of 5 | one knob for the guild's risk appetite |

### 4.1 Model 1 — ε-lexicographic slack (the zero-risk change)

```python
score(trial) = points_for_tier(T) + EPS * slack_fraction
slack_fraction = (BUDGET − τ_T) / BUDGET        ∈ [0, 1)
```

With four trials the tie-break term totals < 4·EPS. Choose
`EPS · TRIAL_SKILLS_PER_WEEK < TRIAL_POINTS_PER_TIER`, e.g. `EPS = 0.5` → total
tie-break ≤ 2.0 ≪ 100. **Provable**: the tie-break can never outrank a tier, so
the argmax's *deterministic point total is unchanged* while the argmax *set* is
narrowed to its safest members. This is not a risk model; it is a strictly
dominating refinement of the current objective, and it needs nothing new from
`simulate_race`.

### 4.2 Model 2 — common-shock survival (the recommended default)

Under `R̃ = R·e^ε`:

```
S(t) = Φ( ln(3600 / τ_t) / σ_ε )        [log-normal shock]
     ≈ Φ( (3600 − τ_t) / (σ_ε · τ_t) )  [normal, first order]
```

**This needs only τ_t** — i.e. `TierStep.cumulative_time`, which the timeline
already holds. It costs *nothing* in the hot loop: not one extra floating-point
operation per member per tier. Measured z at the marginal tier for σ_ε = 8%:
1.72, 0.89, 0.35, 2.11 → S = 0.957, 0.813, 0.637, 0.983.

**Free robust variant.** Because the shock is multiplicative, scaling every rate
by (1−k) is *identical* to shrinking the deadline to 3600(1−k). So

```
tier_robust = max t such that τ_t ≤ BUDGET · (1 − k)
```

is a **scenario min-max answer read straight off the existing timeline** — no
second simulation, no extra arithmetic. "This plan still makes tier 11 if we are
10% slower than modelled" is a sentence the officers will understand, and it is
free.

### 4.3 Model 3 — dropout-aware (+6.4%)

Adds `Σ_m r_m(t)²` per tier, hence k_eff and CV_drop. Measured
0.0655 → 0.0697 ms/race: **+6.4%**, i.e. ~3 s on a 42 s optimize step.

**Implementation constraint — bit-exactness.** `simulate_race` carries a stern
warning that re-associating the rate sum shifts ~1 ULP and sends the search down
a different path. The sum of squares must therefore be added *without* touching
the rate sum. The safe pattern:

```python
rates = [success(level, tier, sb, b) * double * wp / asec
         for level, sb, b, double, wp, asec in prepared]
party_rate = sum(rates)                 # same values, same order, same Neumaier sum
sum_sq     = sum(r * r for r in rates)
```

**Verified**: `sum(list)` and `sum(genexp)` over identical float sequences agreed
in 25 000/25 000 trials — CPython's compensated float fast path is
iterator-based, so materialising the list first is bit-identical. A golden-value
test must pin this anyway.

*Assumption to flag:* does an absentee still inflate `effective_target` via N?
Conservatively **yes** (the roster is fixed at sign-up). This makes the marginal
member asymmetric: they cost 1% of target *certainly* and add rate only
*probabilistically* — which is a real strategic conclusion the current model
cannot reach.

**`q_m` from real data.** `signup.py` already distinguishes members who *ticked*
a trial from members the optimizer *filled* in. Those deserve different q
(`Q_SIGNED_UP` ≈ 0.95, `Q_FILLED` ≈ 0.6). That turns the sign-up page from a
courtesy list into a genuine risk input.

### 4.4 Model 4 — diffusive term (defer)

σ²_diff contributes ~1% of σ_total in the measured regime, so it is not worth
paying for as a default. But the naive implementation's +60% is an artefact of
recomputing tier-independent factors in the loop. Expand:

```
W²[p(1+3δ) − p²(1+δ)²]/a  =  c₁·p − c₂·p²,
        c₁ = W²(1+3δ)/a,  c₂ = W²(1+δ)²/a      ← both tier-INDEPENDENT
```

so `c₁, c₂` belong in `_prepare_member` (which exists precisely for this), and
the loop cost falls to two multiply-adds on a `p` that is already in a register —
call it +10–15%. Worth doing only if calibration (§6) shows the tails need it.

### 4.5 Model 5 — scenario quadrature, and why per-trial Φ is not enough

**A correlation bug lurks in the naive version.** The common shock ε of Model 2 is
*shared* across all four trials — `TARGET_SCALE`, the 400 coefficient and the buff
status are the same numbers in every party. Summing four independent Φ's gets
E[points] right (expectation is linear) but gets the *distribution* of the weekly
total badly wrong: it will understate the chance of a bad week.

The fix is elegant and nearly free. **Condition on ε and the week becomes
deterministic:**

1. Take a 5–7 node Gauss–Hermite grid `{ε_j, w_j}` for N(0, σ_ε²).
2. For each node, each trial's tier is `max t with τ_t ≤ 3600·e^{ε_j}` — a
   *threshold read* off the timeline that is already computed.
3. The weekly total is then a 5–7 atom mixture; convolve the independent
   (member-specific dropout) part within each node if Model 3 is enabled.

Cost: ~7 binary searches over a 15-element list, per assignment. Zero measurable
impact. From the resulting distribution:

```
quantile objective:  maximise the 10th percentile of weekly points
CVaR objective:      maximise E[ points | points ≤ q₁₀ ]
```

"The score we beat nine weeks in ten" is a far better thing to publish than a
point estimate, and it is the honest answer to the user's question.

### 4.6 Model 6 — utility scalarisations

Given §4.5's atoms, both are one line:

```
mean–variance:  E[pts] − γ·Var[pts]
entropic:       −(1/θ)·ln E[ e^{−θ·pts} ]         (additive over independent trials)
```

The entropic (exponential-utility) certainty equivalent is smooth, has no
variance-of-a-variance pathologies, and gives the guild exactly one knob. Keep
one of these as `TRIAL_RISK_UTILITY` and default it to `"expected"` (γ = θ = 0).

---

## 5. Optimization routines

The models above change *what* is scored. These change *how* it is searched.
Note the happy accident: **smoothing the objective should make the existing
search strictly better**, because the plateaus that `marginal_greedy` and
`hill_climb` currently grope across become slopes. A move that buys 40 seconds
toward the next tier is currently invisible; under Model 2 it is a positive delta.

**R1 — drop-in objective swap.** `AssignmentScorer.party_points` returns `float`
instead of `int`; every constructor and refiner is untouched. Two adjustments:
`_construct_marginal_greedy` and `_fill_bench` compare `gain < 0` / `> best_delta`
and should switch to a tolerance (`gain < -TOL`) so float noise cannot make a
neutral move look harmful; and `OPT_SA_T_END = 0.5` is now *warm* relative to the
new sub-tier structure (deltas of 0.1–20 rather than multiples of 100) — drop it
to ~0.05, or rely on the terminal `hill_climb`.

**R2 — two-stage lexicographic (the safe rollout).** Run the existing search to
its deterministic optimum, *then* a second `hill_climb` restricted to moves with
Δpoints ≥ 0, maximising safety. Guarantees no point regression by construction,
and the scorer cache is already hot, so the second pass is nearly free. **This is
how to ship first.**

**R3 — graduated smoothing (continuation / homotopy).** Start the GA and SA with
an inflated σ (a very smooth, highly informative surface) and anneal σ down to the
calibrated value across generations / the cooling schedule. Costs nothing, and is
the standard remedy for exactly the plateau pathology documented in
`_construct_marginal_greedy`. Plausible upside: **more deterministic tiers than
today**, not fewer.

**R4 — Pareto archive.** Keep a non-dominated (points, safety) elite set in
`_run_genetic` and publish the frontier on the trials page: "4900 pts at 61%
confidence, or 4800 at 94%". Cost is bookkeeping only. Lets the officers choose
rather than making the guild's risk appetite a config constant.

**R5 — scenario min-max.** Lexicographic on `(tier_robust, tier_nominal, slack)`
using §4.2's free haircut read. The most conservative option available, at zero
cost.

**R6 — Monte Carlo validator (offline only).** Extend `optimize_bakeoff.py` with a
common-random-numbers race simulator (sample the Bernoullis, resample turnout,
10k paths) to check the analytic Φ against truth. **Must not** land on the build
path. This is what earns the right to trust the closed forms.

**R7 — bake-off axis change.** The harness currently ranks on deterministic points
alone, which cannot see the improvement. It must report **deterministic points,
E[points], and P(≥ deterministic tier)** per strategy, so the change can be
proven not to cost tiers.

---

## 6. Recommended phasing

**Phase 0 — instrument, change nothing.** Add to `TierStep`/`TrialResult` the
slack, `k_eff`, σ decomposition and `S(t)` per tier; carry `RISK_LOOKAHEAD_TIERS`
(default 2) so the race records one or two tiers past the failure for the upside
terms; publish it all to `trials.json`. The objective stays integral. Zero risk,
and it puts the §1.1 measurement in front of the guild on live data every day.

**Phase 1 — Model 1 + R2.** ε-lexicographic slack, plus the point-preserving
safety pass. *Provably* cannot lose a point. This alone captures most of the 54.7
point spread.

**Phase 2 — Models 2 + 3, behind `TRIAL_RISK_MODEL`.** E[points] becomes the
objective; add R3 continuation and R7's bake-off axes. Gate on a regression test
asserting no deterministic-point loss on both live rosters.

**Phase 3 — Model 5 + presentation.** Scenario quadrature, the weekly-total
distribution, and the page copy: "Tier 11 (60% — this one is a coin flip)" with a
robust tier alongside. Add R4 if the officers want the choice.

**Deferred**: Model 4 (until calibration demands it), Model 6 (until someone
articulates a risk appetite).

### Calibration (the part that makes σ_ε honest)

σ_ε and q are working assumptions in exactly the style the repo already uses. The
calibration path is a physicist's: Phase 0 writes the predicted `S(t)` to
`trials.json` each week; the tier actually achieved is observable (the
`guild_updated` captures, or a column on the sheet). After ~10 draws, a
**PIT / reliability histogram** of predicted-vs-achieved tiers gives σ_ε directly
— and if the pulls come out flat, that is the empirical proof the whole model
deserves. Until then, ship Model 1's lexicographic ordering so an uncalibrated σ
cannot cost a real tier.

---

## 7. Risks

| risk | severity | mitigation |
|---|---|---|
| The objective change reshuffles every party, as the ULP note warns | cosmetic but alarming | expected and documented; state it in the commit and on the page |
| An uncalibrated σ trades a real tier for imaginary safety | **high** | Phases 0–1 are lexicographic and cannot; Phase 2 gated on a no-regression test on both live rosters |
| Approximation error in Φ (CLT, delta method, phase independence) | medium | R6 Monte Carlo validator; the nested-events structure of §3 is exact, only S(t) is approximated |
| Cross-trial correlation understated → optimistic weekly tails | medium | Model 5's scenario quadrature is the correct treatment, and is free |
| `signup.py` reuses the trials optimum as its ceiling; the meaning of its "swaps to reach optimal" list changes | medium | update both together; the swap annotations become "gains X expected points" |
| Publishing "89%" invites argument with the officers | low | frame as a range with a robust tier; it is also an *opportunity* — it is the first honest number the page will have shown |
| Runtime | low | measured: Model 2 = 0%, Model 3 = +6.4% (~3 s on a 42 s step), against a ~10 min CI budget |

## 8. Verification plan

1. **Bit-exactness**: golden `party_rate` values for a fixed party/tier survive
   the `rates` list refactor, exactly (`==`, not `pytest.approx`).
2. **σ → 0 reduction**: with all σ set to 0, `E[points] == points_for_tier(tier_reached)`
   exactly, for every party in a fixed roster sweep.
3. **Monotonicity**: adding slack (equivalently raising a rate) never lowers
   `S(t)` for any t, and never lowers E[points].
4. **Nesting**: `S(t)` is non-increasing in t; the tier atoms are non-negative
   and sum to 1 within tolerance.
5. **Lexicographic guarantee** (Phase 1): on fixed rosters, the ε-objective's
   argmax has the *same* deterministic point total as the current argmax.
6. **No-regression** (Phase 2): total deterministic points on the live SC and LI
   rosters ≥ the current shipped result at the same seed.
7. **Monte Carlo agreement** (R6, dev-only): analytic `S(t)` within tolerance of
   10k simulated races, per tier, on three parties spanning k_eff 11–24.
8. **Determinism**: unchanged — everything stays seeded; Gauss–Hermite nodes are
   a fixed table, not sampled.

## 9. Rollback

Every phase is one config line.

- Phase 1: `TRIAL_SLACK_EPS = 0.0` → the tie-break term vanishes and the
  objective is bit-identical to today's.
- Phase 2: `TRIAL_RISK_MODEL = "none"` → `party_points` returns
  `float(points_for_tier(...))` and every strategy behaves as before.
- Phase 3: `TRIAL_RISK_OBJECTIVE = "expected"` → drops the quantile/CVaR layer.
- Full revert: the `git revert` of a single commit per phase; no data migration,
  no schema change beyond additive `trials.json` fields (the page tolerates
  missing keys today via the same degrade-don't-fail rule as `draw.py`).
