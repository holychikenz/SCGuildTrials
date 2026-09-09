# 🗺️ Implementation Plan: Guild Trials patch (2026-08-11) — partial-tier credit, shrine buffs, minimum sign-up level

## Summary

The patch changes three things this repo models, and one it does not:

1. **Partial-tier progress now scores.** `0.5% credit per 1% progress`, up to `~50%` at
   `99.99%` incomplete. This is the headline: **the objective stops being degenerate.**
   Today `points` is a step function of the integer tier, so a member who crosses no
   threshold is worth *exactly* zero and can be seated for free
   (`optimizer._fill_bench`, `signup._fill_open_seats`). Under partial credit every seat
   moves the score, in one direction or the other, and "seat anyone with Δ ≥ 0" stops
   being a free lunch.
2. **Shrine buffs now apply inside Trials.** Two of the five shrines carry *skilling*
   buffs that enter the race directly — **Force → efficiency +0.005/level** and
   **Tempo → action speed +0.005/level** (verified against `guildBuffDetailMap`, §2.1).
   Survey Corps holds both at level 1. The other three (Rarity/Spirit/Scholar) buff
   loot and XP only and must **not** touch the rate model.
3. **Leaders can set a per-trial minimum sign-up level.** A hard eligibility
   constraint the optimizer must respect — and, read the other way, the officers'
   *lever* for actually carrying out the benching the model recommends.

   A corollary worth stating up front, because it inverts the expectation: measured on
   the live rosters (§2.5), the de-degenerated objective wants to bench **nobody**. Every
   seated member clears the ~0.8% break-even and every benched member would *gain* points
   if seated. Today's bench is produced entirely by `TRIAL_PARTY_CAP = 24` — a constant
   its own comment calls *"a magic number"* — so the newly urgent question is not who to
   drop but **whether the cap is real** (§3.7).
4. **Combat is out of scope** (boss haste, participant→monster-speed scaling, the
   Badger/Chameleon/Jellyfish rebalance). Recorded in `research/`, modelled nowhere.

**The thesis.** `research/risk-aware-objective.md` §5 already anticipates all of this
and calls it a "happy accident": *"smoothing the objective should make the existing
search strictly better, because the plateaus that `marginal_greedy` and `hill_climb`
currently grope across become slopes. A move that buys 40 seconds toward the next tier
is currently invisible; under Model 2 it is a positive delta."* **The game has now done
that smoothing for us.** Its pre-written migration note **R1** (`float` points, tolerance
comparisons, a colder SA) is no longer an optional research direction — it is the
required migration, and this plan executes it.

**Key architectural decision — additive, not replacive.** `TrialResult.points` keeps its
exact present meaning (integer, step function of the cleared tier) and a **new**
`credit_points: float` carries the partial-credit score. One config line,
`TRIAL_PARTIAL_CREDIT_RATE`, selects which the optimizer maximises; at its shipped
default of `0.0` the two are bit-identical, so Phases 1 and 3–5 land with **provably
zero** behaviour change and Phase 2 is the single-line flip the repo's rollback
discipline demands. The same trick keeps ~60 existing tests untouched (§7).

**Confidence.** The shrine numbers and the guild-point cost curves are read from the
real dump at `/Users/morgan/pie/farm/cowstuff/milkyway_client_info.json`; every quantitative
claim in §2.2–§2.5 is measured on this repo's own model, and §2.5 on the **live** SC/LI
rosters. Two things are *not* verified and gate Phase 2 — see §3.

---

## 1. Scope

| In | Out |
|---|---|
| `src/config.py`, `src/trials.py`, `src/optimizer.py`, `src/signup.py`, `src/draw.py`, `src/build.py` | anything combat |
| `src/calibrate.py`, `src/simulate_trial.py`, `src/optimize_bakeoff.py` (dev-only, must not drift) | the guild-credit exchange rework (no model touches credits) |
| `tests/test_trials.py`, `test_optimizer.py`, `test_signup.py`, `test_draw.py` | pinned-message display |
| `research/` (two new notes) | the post-trial Stats modal *scraper* (sibling repo) |

---

## 2. Verified data and measurements (do not re-derive)

### 2.1 Guild shrine skilling buffs — from `guildBuffDetailMap`

Source: `/Users/morgan/pie/farm/cowstuff/milkyway_client_info.json`, `gameVersion
v1.20260715.0`, `versionTimestamp 2026-07-16T03:24:51Z`. **This dump is PRE-patch**
(Phase 0 refreshes it). Ten buffs, each keyed to a shrine and flagged `isCombat`:

| buff hrid | shrine | `isCombat` | `typeHrid` | value | enters the race? |
|---|---|---|---|---|---|
| `force_skilling` | `/guild_shrines/force` | false | `/buff_types/efficiency` | **flat 0.005 + 0.005/level** | **YES** → `work_power` |
| `tempo_skilling` | `/guild_shrines/tempo` | false | `/buff_types/action_speed` | **flat 0.005 + 0.005/level** | **YES** → `action_seconds` |
| `rarity_skilling` | `/guild_shrines/rarity` | false | `/buff_types/rare_find` | flat 0.01 + 0.01/level | no — loot |
| `spirit_skilling` | `/guild_shrines/spirit` | false | `/buff_types/essence_find` | flat 0.02 + 0.02/level | no — loot |
| `scholar_skilling` | `/guild_shrines/scholar` | false | `/buff_types/wisdom` | flat 0.005 + 0.005/level | no — XP |
| `force_combat` | force | true | `damage` ratio 0.003/lvl | | no |
| `tempo_combat` | tempo | true | `attack_speed` 0.004/lvl, `cast_speed` 0.004/lvl | | no |
| `spirit_combat` | spirit | true | `max_hitpoints` / `max_manapoints` 0.01/lvl | | no |
| `rarity_combat` | rarity | true | `rare_find` 0.01/lvl | | no |
| `scholar_combat` | scholar | true | `wisdom` 0.005/lvl | | no |

**Cross-check that validates the whole reading.** The patch note says *"Rare Find 1% →
1.5% per level, Essence Find 2% → 3% per level"*. The pre-patch dump has `rare_find`
at exactly `0.01/level` and `essence_find` at exactly `0.02/level`. The notes therefore
(a) refer to these buff values, (b) confirm the in-game rule
`flatBoost + (level-1)*flatBoostLevelBonus = per_level * level` that `config.py:560-566`
already relies on for guild buildings, and (c) tell us **Force and Tempo were not
re-tuned** — only made applicable inside Trials. The `0.005/level` figures above are
current.

**Cost curves (verbatim).** All five shrines share one `guildPointCosts` ladder, exactly
**double** the building ladder: `1:1000, 2:1350, 3:1800, 4:2450, 5:3300, 6:4500, 7:6050,
8:8150, 9:11050, 10:14900, 11:20100, 12:27150, 13:36650, 14:49450, 15:66800, 16:90150,
17:121700, 18:164300, 19:221800, 20:299450`; `maxLevel = 20`.

**A second, separate ladder exists and is an open question (§3.4).** Each
`guildBuffDetailMap` entry carries its *own* `levelCosts` 1..20 priced in
`guildTokenCost` + `creditCosts` (guild credits). So a shrine level (guild points) and a
buff level (tokens + credits) are distinct. The capture in
`research/trial-messages.md:154-160` records `"/guild_shrines/force": 1,
"/guild_shrines/tempo": 1` inside `guildBuildingLevelMap` — that is the **shrine** level;
the **buff** level is not in any capture this repo holds. The patch's new
`[View Buffs]` button is the intended source.

### 2.2 The partial-credit rule, reduced to a formula

`0.5% credit per 1% progress`, and `99.99% → ~50%`, is a pure linear rule of slope
`0.5` with **no separate cap** — `0.5 × 99.99% = 49.995% ≈ 50%`. So, with `f` the
fraction of the first *uncleared* tier's work completed at the buzzer and `T` the highest
tier cleared:

```
creditTiers = T + ρ·f            with ρ = TRIAL_PARTIAL_CREDIT_RATE = 0.5
points      = 0                              if creditTiers == 0
            = 100 + 100 · creditTiers        otherwise
```

The objective is therefore **a ramp of height `ρ·100` followed by a step of
`(1−ρ)·100`** at each tier boundary — the old 100-point cliff is *halved*, not removed.
Both halves matter: the ramp is what kills the degeneracy, the residual step is why
`_compound_reshuffle_into` still has a job.

`f` needs no new simulation. `simulate_race` already records the failed tier in
`timeline` with its `time_to_clear`, and `research/risk-aware-objective.md:63-77` already
names this as information *"already in the return value and being discarded by
`.points`"*:

```
f = (BUDGET − tier_clear_seconds(result)) / failed_step.time_to_clear
```

### 2.3 Measured: the degeneracy, and where the break-even sits

Synthetic 20-strong Foraging party (levels 130…88, tier 11 reached, margin 10.3%,
`f = 0.228`). One extra member is added; `old Δ` is today's objective, `new Δ` is
partial credit:

| candidate level | share of party rate | old Δ | **new Δ** | margin after |
|---|---|---|---|---|
| 140 | 17.3% | **0** | +14.93 | 0.1996 |
| 120 | 7.4% | **0** | +6.45 | 0.1541 |
| 110 | 3.4% | **0** | +3.69 | 0.1334 |
| 100 | 1.9% | **0** | +2.12 | 0.1198 |
| 90 | 1.7% | **0** | +1.27 | 0.1127 |
| 70 | 1.4% | **0** | +0.38 | 0.1054 |
| **60** | **1.1%** | **0** | **+0.10** | 0.1032 |
| **50** | **1.0%** | **0** | **−0.12** | 0.1015 |
| 30 | 0.6% | **0** | −0.47 | 0.0990 |
| 10 | 0.2% | **0** | −0.77 | 0.0968 |

Two facts, both load-bear:

* **Every** candidate from level 140 down to level 10 scores `Δ = 0` today. The
  degeneracy is total, and it is why `_fill_bench` could justify itself as "no harm
  done".
* Under partial credit the sign changes between a rate share of **1.1% and 1.0%**,
  matching the theoretical break-even `1/(100 + N) = 1/120 = 0.83%` inflated by the fact
  that an extra head raises the target of *every* tier including the partial one. **A
  member earns their seat iff they contribute more than about 1% of the party's
  throughput at the contested tier** — which is exactly the consequence
  `research/trial-messages.md:325-330` wrote down as a working assumption and could never
  act on.

### 2.4 Measured: monotonicity, and the margin↔credit identity

Sweeping the whole party's levels by a common shift (same fixture):

| shift | tier | `f` | credit points |
|---|---|---|---|
| −40 | 7 | 0.090 | 804.48 |
| −35 | 7 | 0.576 | 828.80 |
| −30 | 8 | 0.130 | 906.50 |
| ±0 | 11 | 0.228 | 1211.40 |
| +15 | 12 | 0.770 | 1338.50 |
| +30 | 14 | 0.085 | 1504.26 |

**`credit_points` is monotone non-decreasing in party throughput** across the whole
sweep, including at every tier crossing — because completing a tier gains `100` while
surrendering at most `ρ·100 = 50` of partial credit. This is not cosmetic: it is the
precondition for the binary search in `trials._cheapest_bumping_level` and for the
"stronger party never scores less" invariants in the test suite. §7 pins it.

Shrinking the same party one member at a time shows the second identity:

| N | tier | margin | `f` | old | credit |
|---|---|---|---|---|---|
| 20 | 11 | 0.1033 | 0.228 | 1200 | 1211.40 |
| 17 | 11 | 0.0723 | 0.150 | 1200 | 1207.52 |
| 14 | 11 | **0.0162** | 0.031 | **1200** | 1201.56 |
| 13 | 10 | 0.2836 | 0.963 | 1100 | 1148.13 |

> ### ⚠ CORRECTION — this subsection's conclusion is WRONG, and the live run refuted it
>
> **Implemented and measured 2026-08-11.** The claim below that "the new objective walks
> off the buzzer by itself" is false. The minimum margin did not improve from 8.1% /
> 24.1% — it **collapsed to 0.09% and 0.04%**, with three of eight live trials banking
> their tier 1–4 seconds inside the hour at `P(holds) ≈ 0.51`.
>
> The first step of the reasoning is sound: *within* a tier, partial credit does price
> the margin linearly. What it misses is that the **residual step at the boundary is
> still worth `(1−ρ)·100 = 50 points`**, which dwarfs any margin the search could buy
> by standing still. So the objective does not walk off the buzzer; it walks off *this*
> tier's buzzer and straight onto the *next* one's, and every extra tier it finds is
> almost by construction held by seconds.
>
> That is nevertheless the **right** gamble — falling short lands on the tier below with
> ~99% partial credit, so reaching wins on expectation by ~24 points — and it is what
> earned Lactose Intolerance **+200 deterministic points**. But it made the
> deterministic score an optimistic estimate, which is why Phase 7 (`E[points]`) was
> promoted from optional to shipped. Full treatment, with the measured table, in
> `research/partial-tier-credit.md` §9.1–§9.3.

`f = 3600·margin / ttc(T+1)`, so **partial credit is a linear read-out of the very time
margin `optimizer._refine_slack` was invented to protect**. At N=14 the lineup holds
tier 11 by 1.6% — 58 seconds — and scores *identically* to the comfortable N=20 lineup
today; under partial credit the comfortable one is worth 9.8 points more. ~~**The new
objective walks off the buzzer by itself.**~~ ← **refuted by the live run; see the
correction above.** What it does *not* do is protect the
*thinnest* trial, because the objective is a **sum** and risk is a **minimum** — which
is precisely the residual job left for the safety passes (§5.3).

### 2.5 Measured on the LIVE rosters (2026-08-11, draw `[Woodcutting, C.Smithing, Crafting, Cooking]`)

Shipped optimizer, `cap = 24`:

| guild | N | trial | tier | margin | `f` | old | credit | best trim |
|---|---|---|---|---|---|---|---|---|
| SC (102) | 24 | Woodcutting | 11 | 0.1370 | 0.248 | 1200 | 1212.40 | none |
| | 24 | C.Smithing | 11 | 0.1310 | 0.219 | 1200 | 1210.93 | none |
| | 24 | Crafting | 11 | 0.1193 | 0.221 | 1200 | 1211.05 | none |
| | 24 | Cooking | 12 | 0.0812 | 0.120 | 1300 | 1305.98 | none |
| | | **total** | | | | **4900** | **4940.37** | bench 6 |
| LI (97) | 24 | Woodcutting | 10 | 0.2601 | 0.590 | 1100 | 1129.50 | none |
| | 24 | C.Smithing | 10 | 0.2710 | 0.675 | 1100 | 1133.75 | none |
| | 24 | Crafting | 10 | 0.2902 | 0.760 | 1100 | 1138.00 | none |
| | 24 | Cooking | 11 | 0.2409 | 0.511 | 1200 | 1225.56 | none |
| | | **total** | | | | **4500** | **4626.82** | bench 1 |

**A result that inverts the obvious expectation, and redirects the plan.**
A greedy trim — repeatedly drop whichever member most *raises* credit points — removes
**nobody**, on all eight parties, on both guilds. Probing the other direction says why:

| guild | trial | weakest seated member's share of party rate | break-even `1/(100+N)` | uncapped growth |
|---|---|---|---|---|
| SC | Woodcutting | 1.57% | 0.81% | +1 → 1213.77 |
| SC | C.Smithing | 1.91% | 0.81% | +1 → 1212.53 |
| SC | Crafting | 1.42% | 0.81% | +1 → 1212.83 |
| SC | Cooking | 3.61% | 0.81% | +1 → 1307.21 |
| LI | Woodcutting | 1.28% | 0.81% | +1 → 1131.24 |
| LI | C.Smithing | **1.03%** | 0.81% | +1 → 1135.95 |
| LI | Crafting | 1.51% | 0.81% | +1 → 1139.94 |
| LI | Cooking | 3.77% | 0.81% | +1 → 1227.61 |

Every seated member clears the break-even, and **every benched member would raise credit
points if the cap allowed it.** The bench today is produced by `TRIAL_PARTY_CAP = 24`
(4 × 24 = 96 seats against 102 and 97 members), not by marginal value. Nobody deserves
benching; the parties want to be *bigger*.

So the plan's centre of gravity moves. The benching machinery must still be made correct
(§5.2) because it binds the moment the roster grows, a low-level skill is drawn (this week
is four production skills, where the roster is deep), or a minimum sign-up level shrinks
the eligible pool — but the *urgent* question partial credit has just exposed is a
different one, and it is §3.7: **is the cap real, and what is its value?** Under the old
step objective that question was unanswerable, because a marginal seat was worth exactly
zero either way. It is now worth 1.2–2.2 points, measurably, per seat.

Also worth recording: partial credit is worth **+40.4 points (0.8%) to SC and +126.8
(2.8%) to LI** on the shipped assignment. LI gains three times as much because its
parties sit mid-ramp (`f ≈ 0.6–0.76`) — i.e. the guild has been earning most of another
tier's worth of credit and seeing none of it.

### 2.6 Measured: what a shrine actually buys, and what it costs

Same synthetic Foraging party, applying Force (efficiency) and/or Tempo (speed) at
`0.005/level`, priced against the shrine guild-point ladder at `2.5` weeks between draws:

| shrine level | `f` | credit points | Δ | cumulative gp | weeks to repay |
|---|---|---|---|---|---|
| none (today, ignoring the live L1s) | 0.228 | 1211.40 | — | — | — |
| L1 Force | 0.235 | 1211.75 | +0.35 | 1 000 | 7 196 |
| L1 Force + L1 Tempo | 0.240 | 1212.01 | +0.61 | 2 000 | 8 233 |
| L5 both | 0.293 | 1214.67 | +3.27 | 19 800 | 15 152 |
| L20 both | 0.493 | 1224.64 | +13.24 | 2 304 200 | 435 239 |

**Two conclusions, and the second is the useful one.** (a) The buffs are *real and must
be modelled* — Force+Tempo at L1 is +0.61 points per trial today and the model is
currently wrong by that much. (b) As an *investment* they are poor: even fully maxed,
Force+Tempo buys **less than one tier** for 2.3M guild points, on a cost ladder twice
the buildings'. The trials page should price shrines **and say plainly that buildings
dominate** — a negative result the guild can act on, and one nobody can currently see.

> **CORRECTION, made during Phase 3 implementation.** The weeks-to-repay column above
> is wrong — too pessimistic by roughly an order of magnitude — because it prices a
> shrine the way `probe_building_upgrade` prices a building: per-trial, and discounted
> by `TRIAL_WEEKS_BETWEEN_DRAWS = 2.5` for the weeks that skill is not drawn. But a
> **building buffs one skill** and so pays only when that skill is drawn, whereas a
> **shrine buffs efficiency or action speed for everyone in every skill** and so pays
> in **all four trials, every week**. Measured correctly by
> `trials.probe_shrine_upgrade`, Force L1→L2 repays in **≈561 weeks** and Tempo L1→L2 in
> **≈806**, against the ~7,196 and ~9,648 tabulated above. Still a bad buy beside a
> building, and still worth publishing as such — but the honest figure is ~13× better
> than this section originally claimed, and `ShrineUpgrade`'s docstring records why.

### 2.7 What the capture already gives us for verification

`research/trial-messages.md:75-101` records `currentTrialsData` carrying, per trial,
`points` (the guild's actual award), `highestTier`, `budgetRemainingMs` and
`tierStartedAtMs`. **That is a complete verification kit for §3.1–§3.2 with no new
tooling**: any excess of `points` over `100 + 100 × highestTier` *is* the partial credit,
and `tierStartedAtMs` + `budgetRemainingMs` gives `f` in time, against which the model's
`ttc` can be checked directly.

---

## 3. Open questions that gate Phase 2 — resolve before flipping `TRIAL_PARTIAL_CREDIT_RATE`

Ranked by how much they move the answer. **Phases 1 and 3–5 ship without any of them.**

### 3.1 Does partial credit apply to GUILD POINTS, or only to item rewards? — BLOCKING
The note reads *"granting partial **rewards**"*. If the credit lands only on the loot
table and the guild-point award stays `100 + 100·highestTier`, then the objective is
**unchanged** and this entire plan reduces to §2.1 (shrines), §4 (min level) and display.
**Resolution:** after the next trial, read `currentTrialsData.points` against
`100 + 100 × highestTier` (§2.7). One capture settles it.

### 3.2 Is `ρ` exactly `0.5`, and is the `100`-point base also pro-rated? — BLOCKING for the constant
Two sub-questions. (a) `0.5` is stated in the notes and is assumed exact.
(b) `points_for_tier` awards a flat `100` "for finishing at all"
(`config.py:484-491`, itself an ASSUMPTION fitted to two observations). Does a party at
99% of tier 1 receive `0`, `50`, or `150`? The plan implements the reading
*"credit is on the per-tier term; the base is awarded iff `creditTiers > 0`"* behind
`TRIAL_PARTIAL_CREDIT_BASE_PRORATED = False`, because it is the only reading consistent
with the existing `points(0) = 0`. **Resolution:** the same capture, on any trial that
fails tier 1 (rare) — or the new per-member Stats modal.

### 3.3 Did the **skilling** headcount penalty change? — HIGH VALUE
Patch note 2 — *"Participant count now scales monster +2% attack/cast speed and +2
ability haste"* — is combat-worded, but it is a *rebalance of how participant count is
applied*, and `HEADCOUNT_PENALTY_PER_MEMBER = 0.01` is the entire basis of the break-even
in §2.3. At 1%/head the break-even is ~1% of party throughput; at 2% it doubles and the
benching picture in §2.5 changes qualitatively. Note the repo *also* still has the
unresolved linear-vs-compounding question (`(1+N/100)` vs `1.01^N`,
`research/trial-messages.md:318-330`). **Resolution:** the refreshed dump (Phase 0), then
a `targetWorkValue` capture at two different party sizes.

### 3.4 Which shrine ladder drives the multiplier, and what are the live levels? — HIGH VALUE
§2.1: shrine level (guild points) and buff level (tokens + credits) are separate. The
capture gives the shrine level (Force 1, Tempo 1); the buff level is unrecorded.
**Resolution:** the new `[View Buffs]` button, which the notes say splits active guild
buffs into Skilling and Combat — i.e. it displays exactly the resolved magnitudes we
need. Until then `GUILD_SHRINE_LEVELS` is a config map with the same "one map serves both
guilds, split it the moment they diverge" caveat `config.py:595-599` already carries for
buildings.

### 3.5 Where does the per-trial minimum level come from as *data*? — DESIGN CHOICE
Three candidates, in ascending friction: a third column in the officers' `Trial
Priority` table (which `draw._parse_priority_block` already walks — §6.4, ~15 lines,
fully backward compatible), a config constant, or a new capture pushed by the
Tampermonkey writer. **Recommendation: the sheet column**, because the officers who set
the minimum in-game are the same people who maintain that tab, and absence of the column
is a clean no-op default.

### 3.6 Does the new Stats modal expose per-member contribution? — OPPORTUNITY, not a gate
*"per-member combat/skilling stats"* would be the first per-member ground truth this
project has ever had, and `src/calibrate.py` is built to consume exactly that: its
`RISK_SIGMA_SYSTEMATIC = 0.0131` exists *because* neck/ring/earring gear and real
enhancement levels are unobserved (`config.py:374-378`). A modal that reports per-member
work would let that constant be measured instead of inferred. Worth a research note and a
sibling-repo scraper task; **out of scope for this plan.**

### 3.7 Is the party cap real, and is it 20 or 24? — NEWLY URGENT, and it cuts both ways
`TRIAL_PARTY_CAP = 24` is flagged in its own comment as *"a magic number"*
(`config.py:195-198`); `research/trial-tabs.md:76` records a **maximum observed 20** for
skilling; and `research/trial-messages.md:267-270` states the 20-cap *"is not confirmed in
any game message"*. §2.5 has just shown that all eight live parties sit exactly on the cap
and would all grow if allowed. The constant is therefore a **first-order source of error,
in whichever direction it is wrong**:

* **If the real cap is 20**, the model seats 24 where only 20 can play, and every
  published tier, margin and probability on both pages is **optimistic** — four phantom
  contributors per party, on parties whose margins run 8–29%.
* **If there is no cap at 24**, the guild is leaving ~5–8 credit points a week on the
  table and the tool is quietly telling it to.

Partial credit is what made this visible: under the step objective a marginal seat was
worth exactly zero, so being wrong about the cap cost nothing measurable. **Resolution:**
one party capture from a trial the guild deliberately over-fills, or the participant counts
in the new post-trial Stats modal. Cheap — and it should be settled before Phase 2's
numbers are published as advice.

Until then Phase 5 should publish the exposure rather than hide it: a per-trial
**marginal-seat line** — *"weakest seated member contributes 1.03% against a 0.81%
break-even; one more seat would be worth +2.2 points"* — which states the sensitivity
without pretending to resolve it.

---

## 4. File changes (2 new, 10 modified, 1 new test file)

### New

| file | purpose |
|---|---|
| `research/partial-tier-credit.md` | The patch notes verbatim; the §2.2 derivation; §2.3–§2.6 measurements; §3's open questions with their resolution recipes; the verification kit of §2.7. The companion-file convention of `research/risk-aware-objective.md`. |
| `research/guild-shrines.md` | §2.1's table, the two ladders, the patch-note cross-check, and the negative investment result of §2.6. |

### Modified

| file | change | phase |
|---|---|---|
| `src/config.py` | 4 new constant blocks (partial credit, shrines, fill policy, safety tolerances); one reworded comment block on `_refine_slack` | 2,3,5 |
| `src/trials.py` | `tier_progress_fraction`, `credit_tiers`, `points_for_result`; `TierStep.progress_fraction`; `TrialResult.{partial_fraction, credit_points}`; `WeekResult.total_credit_points`; shrine terms in `member_bonuses`/`_prepare_member`; `BuildingUpgrade.credit_points_gained` + a shrine probe | 1,2,3 |
| `src/optimizer.py` | `AssignmentScorer` scores `credit_points`; tolerance in `_construct_marginal_greedy`, `_fill_bench`, `_refine_slack`; `_refine_slack` re-founded on an admissibility test; eligibility filter; SA temperature | 2,4 |
| `src/signup.py` | `_slack_key` / `_safety_swaps` tolerance (**the silent-regression site**); `_fill_open_seats` policy; `Swap.gain`/`SafetySwap` → float; `SignupPlan` gains credit totals and the min-level report | 2,4 |
| `src/draw.py` | `TrialDraw.min_levels`, parsed optionally from the `Trial Priority` block | 4 |
| `src/build.py` | partial progress on both pages; the points-formula footnote (line 928-931); the "margin is the risk" footnote (1871-1883); "Safety swaps buy odds, never points" (1901-1915); fill chips; upgrades table + shrine rows; min-level section | 5 |
| `src/calibrate.py` | mirror the shrine terms in `_prepare_perturbed`; a `scenario_shrines_off`; partial credit in `expected_points` | 6 |
| `src/simulate_trial.py` | report partial progress so the action-level validator can check `f` | 6 |
| `src/optimize_bakeoff.py` | report deterministic points **and** credit points (`risk-aware-objective.md` R7) | 2 |
| `.github/workflows/deploy.yml` | run `pytest` before the build (see Risk 2) | 0 |

---

## 5. Design decisions, then phasing

### The three decisions that carry the plan

### 5.1 `points` stays; `credit_points` is new

The alternative — mutating `TrialResult.points` to a float — was rejected. It would break
`test_points_formula` (the direct pin on `points = 100 + 100·tier`), the entire
upgrade-probe block (`points_gained == TRIAL_POINTS_PER_TIER`, `draws == 5.0`,
`weeks == 12.5`), every hand-written `== 0` and every page column, and it would destroy
the ability to state "one line reverts this". Keeping both:

* `points` — integer, step, the game's *confirmed-shape* award. Unchanged everywhere.
* `credit_points` — float, the objective. `== float(points)` when `ρ = 0`.
* `BuildingUpgrade.points_gained` stays the **tier**-based integer (so
  `_cheapest_bumping_level`'s binary search and its brute-force-parity test are
  untouched) and gains `credit_points_gained` plus `credit_points_per_level`. Under
  partial credit *every* level buys something, so "cheapest level that buys a tier" and
  "what does one level buy" become two different, both-useful questions — and the
  upgrades table stops printing *"No building can buy another tier this week, at any
  level"* (`build.py:671-674`) and starts printing a number.

### 5.2 Benching: an explicit, priced subsidy

`_fill_bench` exists only because hill-climb requires *strict* improvement and riders
scored `Δ = 0` (`optimizer.py:769-775`). Under partial credit riders score `Δ ≠ 0`, so
**hill-climb already seats everyone worth seating** and `_fill_bench`'s entire
justification — *"a member who crosses no threshold contributes exactly zero — no harm
done"* — evaporates. What is left is a policy question, and it should be one dial:

```python
TRIAL_FILL_MAX_POINT_COST = 0.0   # guild points the guild will spend to seat one more member
```

`0.0` = strict (seat nobody who costs points). Raise it to buy inclusion. The pass keeps
its "greatest Δ first" order, admits `gain >= -TRIAL_FILL_MAX_POINT_COST`, and **records
the cost** so `build.py` can print the bill: *"seating these 4 costs 1.3 guild points"*.
This is the honest form of the user's constraint — we can still include people, but only
after saying what it costs and who decided.

`_fill_bench` also currently runs **after** `_refine_slack`, justified by a measured
"1.2pp of margin for no points" trade (`optimizer.py:955-959`). Under partial credit that
trade costs *points*, which the slack pass was told to preserve. Order becomes
`run_strategy → _fill_bench → _refine_slack`, and both orders are measured on the live
rosters before the change is kept.

### 5.3 The safety passes: from "exactly equal" to "within tolerance"

Two passes currently gate on exact integer point equality, and both must change:

| | today | becomes |
|---|---|---|
| `optimizer._refine_slack` | rank `(sum(pts), min(slack), sum(slack))`, points *"compared as exact ints, so it cannot trade a tier for margin"* | admissible iff `total >= base_total - OPT_SLACK_POINTS_TOLERANCE` **and** `min_slack > base_min`; rank admissible moves by `(min_slack, total)` |
| `signup._safety_swaps` | `key[0] == base_points` | `key[0] >= base_points - SIGNUP_SAFETY_POINTS_TOLERANCE` |

Both tolerances default to `0.0`, which keeps the guarantee as strong as it can be under
a continuous objective and makes the change a no-op if partial credit is off.

Three notes on why this is the right shape, not merely a float-hygiene patch:

* **It unifies two passes the repo already regrets having diverge.** `signup.py:836-841`
  records the lesson learned the hard way: ranking points-first *"only guarantees a move
  never costs a tier"*, and accepting any lexicographic gain *"lets a move through on
  `sum_margin` alone… a page full of advice that fixed nothing."* `_refine_slack` still
  has the weaker form. Giving both the same admissibility test fixes that asymmetry.
* **The old exclusion of points *gains* can now be dropped.** It existed because a live
  probe found a move that gained a tier while crashing that trial's margin to 0.23%.
  Requiring `min_slack` to *strictly rise* forbids that independently, so a
  gain-plus-margin-rise move is unambiguously good and need not be hidden.
* **The tolerance is a stated price, not an epsilon.** `OPT_POINTS_EPS = 1e-9` handles
  float noise; `*_POINTS_TOLERANCE` answers "how many guild points will we pay for
  margin?" — a guild decision, on the page, in the config, with a name.

---

### Phasing

Each phase is independently shippable and independently revertible.

### Phase 0 — refresh the ground truth, change no behaviour

1. Re-fetch `milkyway_client_info.json` in `~/pie/farm/cowstuff` and confirm the version
   bumps past `v1.20260715.0`. Diff `guildBuffDetailMap`, `guildShrineDetailMap`,
   `guildTrialDetailMap` and search for a partial-credit coefficient and a participant
   term (`grep -c partial` was **0** on the pre-patch dump). This is the cheapest possible
   route to resolving §3.1–§3.4 from authoritative data rather than inference.
2. Write the two `research/` notes. Patch notes verbatim, so the reading is auditable.
3. Add a `test` job to `deploy.yml`. **CI currently runs only `python -m src.build`** —
   the suite has never gated a deploy, so a logic regression that does not crash ships
   silently. This plan makes ~15 exact-comparison changes; that is not an acceptable
   risk to carry on a green-because-untested pipeline.

**Verify:** `uv run python -m pytest tests/ -v` green; site builds unchanged.
**Rollback:** delete the notes; revert the workflow.

### Phase 1 — instrument partial progress; the objective stays integral

`research/risk-aware-objective.md` §6 Phase 0, with the field the patch made real.

1. `trials.tier_progress_fraction(result) -> float` — §6.1.
2. `TierStep.progress_fraction: Optional[float]` (populated on the failed step only).
3. `TrialResult.partial_fraction: float`, `TrialResult.credit_points: float`.
   `points` is **untouched**.
4. `WeekResult.total_credit_points: float`; both totals into `trials.json`.
5. `SignupTrial.partial_fraction` / `credit_points`; `SignupPlan.enforced_credit_total`,
   `optimal_credit_total`.
6. `config.TRIAL_PARTIAL_CREDIT_RATE = 0.0` — **shipped off.**

**Verify:** with the rate at `0.0`, `credit_points == float(points)` **exactly** for
every party in a fixed roster sweep; `trials.json` / `signup.json` gain keys and lose
none; `AssignmentScorer.sim_calls` unchanged (`f` is read off the existing timeline, so
this adds **zero** simulations); both live builds produce byte-identical HTML apart from
the new JSON keys.
**Rollback:** the fields are additive and unread; `git revert`.

### Phase 2 — flip the objective (the R1 migration)

Gated on §3.1. `TRIAL_PARTIAL_CREDIT_RATE = 0.5`.

1. **`AssignmentScorer._evaluate` returns `(credit_points, slack)`** — `float` now.
   Rewrite the docstring's *"keeps its exact previous contract — an `int`"* claim
   (`optimizer.py:86-90`); it is no longer true and the comment is load-bearing.
2. **Tolerances.** `config.OPT_POINTS_EPS = 1e-9` (float-noise guard, not a policy) used
   in `_construct_marginal_greedy` (`best[0] < 0` → `< -EPS`), `_fill_bench` (same),
   `_refine_hill_climb` / `_anneal_once` (`delta > best_delta` → `> best_delta + EPS`),
   `_compound_reshuffle_into` (`delta < 0` → `< -EPS`, `gain > 0` → `> EPS`),
   `_improving_swaps` (`total < ceiling` → `< ceiling - EPS`). Exactly R1's instruction.
   *Termination is unaffected either way* — every accepted move strictly increases a
   bounded key over a finite state space, which cannot cycle in `float` any more than in
   `int` — so the epsilon buys determinism, not correctness.
3. **SA temperature.** R1: *"`OPT_SA_T_END = 0.5` is now warm relative to the new
   sub-tier structure (deltas of 0.1–20 rather than multiples of 100) — drop it to
   ~0.05."* Set `OPT_SA_T_START = 15.0`, `OPT_SA_T_END = 0.05`, with the derivation in
   the comment. SA is not in `OPT_ENSEMBLE_PIPELINES` today, but `optimize_bakeoff` runs
   it and a two-orders-of-magnitude-wrong schedule would make the bake-off lie.
4. **Re-found `_refine_slack`** (§5.3 below).
5. **Re-found `signup._safety_swaps`** (§5.3 below). **This is the highest-risk edit in
   the plan:** its admissibility test is `key[0] == base_points`, an *exact* equality on
   what is now a float, which will admit essentially nothing and empty the safety-swap
   list **silently**. No current test would fail — `test_safety_swaps_*` would pass
   vacuously.
6. **The fill policy** (§5.2 below).
7. `optimize_bakeoff` reports both totals (R7).

**Verify:** §7's tests; no deterministic-point regression on either live roster at the
same seed (`risk-aware-objective.md` §8.6); runtime within +10% (`f` costs no
simulations, the re-founded passes may iterate more); `TRIAL_PARTIAL_CREDIT_RATE = 0.0`
reproduces Phase-1 output **bit-exactly**, including the chosen parties.
**Rollback:** `TRIAL_PARTIAL_CREDIT_RATE = 0.0`. One line.

### Phase 3 — shrine buffs

1. `config`: `GUILD_SHRINE_NAMES`, `GUILD_SHRINE_SKILLING_BUFF`, `GUILD_SHRINE_LEVELS`
   (Force 1, Tempo 1, rest 0 — from the capture), `GUILD_SHRINE_POINT_COSTS`,
   `SHRINE_BUFFS_APPLY_IN_TRIALS = True`.
2. `trials.guild_shrine_bonuses() -> tuple[float, float]` — `(speed, efficiency)`,
   guild-wide, resolved **once per race** exactly as
   `guild_building_skill_levels` is.
3. `MemberBonuses` gains **separate** `shrine_speed` / `shrine_efficiency` fields.
   **This is deliberate and it follows the existing precedent**: `building_levels` is
   already a separate field rather than folded into `level`, because it is guild-wide
   rather than member-owned. Folding the shrine terms into `speed`/`efficiency` would
   break ~13 tests that reconstruct those sums term by term (including two that assert
   `efficiency == 0.0` exactly for Enhancing). Separate fields keep every one of them
   passing *and* state the guild-wide/member-owned distinction in the type.
4. `_prepare_member` composes: `work_power(level, efficiency + shrine_efficiency)`,
   `action_seconds(skill, speed + shrine_speed)`.
5. `probe_shrine_upgrade`, mirroring `probe_building_upgrade`, and a shrine block in the
   upgrades table — with §2.6's verdict in the copy.

**Verify:** `SHRINE_BUFFS_APPLY_IN_TRIALS = False` **or** all-zero levels ⇒ rates
bit-identical to Phase 2; `calibrate.selftest`'s `worst < 1e-9` golden still passes
(this is why `calibrate._prepare_perturbed` must be edited in the same commit); the two
loot shrines and the XP shrine provably do not enter `rate`.
**Rollback:** `SHRINE_BUFFS_APPLY_IN_TRIALS = False`. One line.

### Phase 4 — per-trial minimum sign-up level

1. `draw.TrialDraw.min_levels: dict[str, Optional[int]]`, read from the column two to the
   right of the `Trial Priority` banner when it holds an integer, else `None`. Absent
   column ⇒ every value `None` ⇒ **no constraint**, so the feature is inert until the
   officers fill it in. `_parse_legacy_block` returns `None`s (the legacy layout has no
   such column).
2. Threading: `run_week(..., min_levels=None)` → `optimize(..., min_levels=None)` →
   `AssignmentScorer`; `signup.plan(..., min_levels=None)`.
3. **Enforcement, belt and braces.** (a) An ineligible `(member, skill)` pair is treated
   exactly like a member with no usable level — `_prepare_member` returns `None`, so they
   contribute `0`. Under Phase 2's objective a zero-rate member *always* lowers credit
   points, so **the search benches them unaided**; this is the first constraint the
   de-degenerated objective enforces for free. (b) Because "the objective will handle it"
   is not a guarantee, a final hard filter in `optimize()` and `signup.plan()` removes
   ineligible members from every party and asserts none remain. (b) is the enforcement;
   (a) is what stops the search wasting time on illegal states.
4. **The recommendation, which is the actually valuable half.** For each trial report the
   minimum level that would reproduce the model's own party — `min(level of seated
   members)` — plus the count it would exclude and the credit points it would gain. The
   minimum-level setting is the officers' only *mechanism* for enforcing a bench; the
   model has never before been able to tell them what to type into it.
5. Sign-up page: flag any volunteer below their trial's minimum in red beside the
   existing missing-from-roster treatment — they ticked a box the game will not honour.

**Verify:** no ineligible member in any shipped party or `signup.json` roster; with no
minimums set, output is byte-identical to Phase 3; a fixture with a minimum above every
level yields an empty party scoring `0` rather than an exception.
**Rollback:** clear the sheet column.

### Phase 5 — pages, JSON and copy

The `build.py` map is in the appendix; the copy that **must** change:

| line | today | must become |
|---|---|---|
| 928-931 | *"`points(T) = 100 + 100*T` for the highest tier T (0 if tier 1 is not cleared). Fits the only observed data…"* | the §2.2 formula, the `ρ = 0.5` citation, and §3.1–§3.2 flagged as open |
| 1871-1883 | *"**The margin is the risk.** Points are a *step* function of the tier reached, so a trial that banks its tier with nine seconds left scores exactly the same as one that banks it with ten minutes left"* | **no longer true.** Points now price the margin linearly (§2.4); what survives is that the objective is a *sum* and risk is a *minimum* |
| 1901-1915 | *"**Safety swaps buy odds, never points.** … leave the score *exactly* as it is"* | *"…cost at most `SIGNUP_SAFETY_POINTS_TOLERANCE` points"* — the guarantee weakens and the page must say so |
| 692-707 | upgrades prose: *"until the party clears another tier"* | every level now buys measurable points; add points-per-level, and the shrine verdict from §2.6 |
| 1443/1445 | chips `Fill +{n}` / `Fill (safe)` | `Fill +2.1` / `Fill −0.4 (rider)` — a rider now has a price and it must be on the page |
| 1857-1863 | *"A fill is only suggested where it does not *lower* a party's tier"* | the `TRIAL_FILL_MAX_POINT_COST` policy, and the bill |
| 319-321, 724-726, 1496-1498 | `tier reached 11 · 1200 points` | `tier 11 + 23% into 12 · 1211.4 points` |

Additions: a `progress` column on the timeline's failed row; a **marginal-seat line** per
trial card (§3.7 — weakest seated member's share, the break-even, and what one more seat
would be worth); a "minimum level" line per trial card; shrine rows in the upgrades table;
assumptions-list entries for partial credit, shrines, minimum levels and the unconfirmed
cap.

**Verify:** both pages render for both guilds; no `KeyError` on a `signup.json` written
by the previous phase (the degrade-don't-fail rule `draw.py` already follows);
`_prob`/`_pct`/`_num` handle fractional points.
**Rollback:** copy-only; `git revert`.

### Phase 6 — validate and recalibrate

1. `simulate_trial.py` reports realised partial progress; check the model's `f` against
   20 000 action-level rolls, as `RISK_SIGMA_SYSTEMATIC` was checked.
2. `calibrate.py`: mirror the shrine terms (or the σ→0 golden fails), add
   `scenario_shrines_off`, and extend `expected_points` (`calibrate.py:729-743`) with the
   partial term.
3. Against the first post-patch capture, check `points` vs `100 + 100·highestTier` (§2.7)
   and the model's `f` against `tierStartedAtMs`/`budgetRemainingMs`.
4. Re-search `tests/test_signup.py::_thin_scenario` (§7.3).

### Phase 7 — OPTIONAL: `E[points]` as the objective

Recorded because the patch has made it *cheap and well-posed*, not because it should ship
with the rest.

`research/risk-aware-objective.md` §4 Model 2 was deferred partly because a step
objective makes an expectation a sum of tail probabilities. Under partial credit, points
are a smooth monotone function of the realised clearing times, so with the already
calibrated multiplicative shock `ε ~ N(0, σ²)`, `σ = hypot(clear_sigma,
RISK_SIGMA_SYSTEMATIC)`:

```
τ_t(ε) = τ_t · e^(−ε)          (a rate shock is exactly a clock shock)
T(ε)   = max{ t : τ_t e^(−ε) ≤ B }
f(ε)   = (B − τ_T e^(−ε)) / ((τ_{T+1} − τ_T) e^(−ε))
E[pts] = ∫ points(T(ε), f(ε)) φ(ε/σ)/σ dε      — 15–20 Gauss–Hermite nodes
```

Every `τ_t` is already in `timeline`, so this needs **no new simulation** — just ~20
re-reads of a curve the scorer already computed. It subsumes both the step objective and
the safety pass: maximising `E[points]` automatically prefers margin, per trial, in the
correct currency. Keep it **out of the hot loop** (the scorer caches `(points, slack)`,
not timelines, and caching 87k timelines would not fit) — make it a final refinement pass
and a reported number, behind `TRIAL_RISK_OBJECTIVE`.

---

## 6. Exact signatures

### 6.1 `src/trials.py`

```python
def tier_progress_fraction(result: "TrialResult") -> float:
    """Fraction of the first UNCLEARED tier's work the party completed at the buzzer.

    In [0, 1). 0.0 when nothing was in progress: the party could not move at all
    (party_rate <= 0, so the failed step has time_to_clear None), or the race ran to
    _MAX_TIER and no failed step exists.

    Costs NOTHING: simulate_race already records the failed tier's time_to_clear, and
    tier_clear_seconds already reports the clock at the last banked tier. This is the
    information research/risk-aware-objective.md:63-77 describes as "already in the
    return value and being discarded by .points".
    """
    budget = config.TRIAL_TIME_BUDGET_SECONDS
    spent = tier_clear_seconds(result) or 0.0
    for step in result.timeline:
        if not step.cleared:
            if step.time_to_clear is None or step.time_to_clear <= 0:
                return 0.0
            return _clamp((budget - spent) / step.time_to_clear, 0.0, 1.0)
    return 0.0


def credit_tiers(tier_reached: int, progress_fraction: float,
                 rate: Optional[float] = None) -> float:
    """tier_reached + rate * progress_fraction — the tier credit the trial earns.

    ``rate`` defaults to config.TRIAL_PARTIAL_CREDIT_RATE (0.0 = the pre-2026-08-11
    step function, exactly).
    """


def points_for_result(result: "TrialResult",
                      rate: Optional[float] = None) -> float:
    """Guild points including partial-tier credit.

    == float(points_for_tier(result.tier_reached)) EXACTLY when the rate is 0.0, which
    is the shipped default and the one-line rollback.
    """
```

`TierStep` gains `progress_fraction: Optional[float] = None`.
`TrialResult` gains `partial_fraction: float = 0.0` and `credit_points: float = 0.0`;
`points: int` is untouched. `WeekResult` gains `total_credit_points: float = 0.0`.

```python
def guild_shrine_bonuses() -> tuple[float, float]:
    """(speed, efficiency) the guild's shrines grant EVERY member inside a trial.

    Guild-wide, not per-member — the same shape as guild_building_skill_levels. Only
    Force (efficiency) and Tempo (action speed) enter the race; Rarity and Spirit buff
    LOOT and Scholar buffs XP, none of which the tier race reads. Returns (0.0, 0.0)
    when config.SHRINE_BUFFS_APPLY_IN_TRIALS is False (the pre-patch behaviour).
    """
```

`MemberBonuses` gains `shrine_speed: float = 0.0`, `shrine_efficiency: float = 0.0`.

### 6.2 `src/config.py`

```python
# --- Partial-tier credit (patch 2026-08-11) ---------------------------------
# "Partial-tier progress is tracked when a trial ends, granting partial rewards.
#  0.5% credit per 1% progress, up to 50% credit at 99.99% but incomplete."
# A pure linear rule of slope 0.5 with no separate cap (0.5 * 99.99% = 49.995%).
#   creditTiers = tier_reached + TRIAL_PARTIAL_CREDIT_RATE * progress_fraction
# The objective is therefore a RAMP of height 50 followed by a STEP of 50 at each
# tier boundary: the old 100-point cliff is halved, not removed, which is why
# signup._compound_reshuffle_into still has work to do.
#
# SET TO 0.0 (the shipped default until the capture in research/partial-tier-credit.md
# confirms the credit lands on GUILD POINTS and not only on the loot table) to restore
# the pre-patch step function EXACTLY: credit_points == float(points) bit for bit.
TRIAL_PARTIAL_CREDIT_RATE = 0.0
# Whether the flat TRIAL_POINTS_BASE is also pro-rated. False = awarded in full once
# any credit is earned, matching the existing points(0) == 0. UNCONFIRMED (see §3.2).
TRIAL_PARTIAL_CREDIT_BASE_PRORATED = False

# --- Float-noise guard, NOT a policy ----------------------------------------
# With integer points, "strictly improving" was exact. With partial credit the deltas
# are floats and a re-associated sum can differ by an ULP (see trials._prepare_member
# on why that matters here: a one-ULP change once reshuffled every SC party for no
# gain). Termination never depended on integrality — a strictly increasing bounded key
# over a finite state space cannot cycle — so this buys determinism, not correctness.
OPT_POINTS_EPS = 1e-9

# --- How many guild points will we pay for time margin? ---------------------
# 0.0 keeps the guarantee as strong as a continuous objective allows.
OPT_SLACK_POINTS_TOLERANCE = 0.0
SIGNUP_SAFETY_POINTS_TOLERANCE = 0.0

# --- How many guild points will we pay to include one more member? ----------
# Under the old step objective a marginal member was worth EXACTLY zero, so seating
# them was free and optimizer._fill_bench could call it "no harm done". Partial credit
# prices them: a member earns their seat iff they contribute more than ~1% of the
# party's throughput at the contested tier (measured: the sign changes between a 1.1%
# and a 1.0% share -- research/partial-tier-credit.md §2.3). Inclusion is now a
# purchase, so it gets a price rather than a silent default, and the page prints the
# bill. 0.0 = seat nobody who costs points.
TRIAL_FILL_MAX_POINT_COST = 0.0
```

Shrine block: `GUILD_SHRINE_NAMES`, `GUILD_SHRINE_SKILLING_BUFF` (§2.1's five entries,
with the three non-race buffs present and commented as deliberately unmodelled),
`GUILD_SHRINE_LEVELS = {"force": 1, "tempo": 1, "rarity": 0, "spirit": 0, "scholar": 0}`,
`GUILD_SHRINE_MAX_LEVEL = 20`, `GUILD_SHRINE_POINT_COSTS` (§2.1 verbatim),
`SHRINE_BUFFS_APPLY_IN_TRIALS = True`.

### 6.3 `src/optimizer.py`

```python
class AssignmentScorer:
    def party_points(self, skill_idx: int, member_ids) -> float:   # was -> int
        """Credit points (partial-tier credit included) for this party.

        WAS AN INT. With config.TRIAL_PARTIAL_CREDIT_RATE == 0.0 this returns
        float(simulate_race(...).points) exactly, so every strategy's trajectory is
        bit-identical to the pre-patch code; with credit on, the value is continuous
        and callers must compare against config.OPT_POINTS_EPS rather than 0.
        """

def _refine_slack(parties, scorer) -> Parties:
    """...admissible iff total >= base_total - OPT_SLACK_POINTS_TOLERANCE AND
    min_slack > base_min; admissible moves ranked by (min_slack, total)."""

def optimize(members, skills, seed=None, cap=None, target_scale=None,
             strategy=None, min_levels: Optional[dict[str, int]] = None) -> Assignment:
```

### 6.4 `src/draw.py`

`TrialDraw` gains `min_levels: dict[str, Optional[int]] = field(default_factory=dict)`;
`_parse_priority_block` reads `col + 2` per skill row and coerces via `reader._to_int`
(blank / non-numeric / absent column ⇒ `None` ⇒ unconstrained). `_parse_legacy_block`
returns all-`None`. `EXPECTED_TRIALS` and every existing guard are untouched.

---

## 7. Test plan

### 7.1 Survives untouched (by design)

The additive `points` / `credit_points` split and the separate `MemberBonuses` shrine
fields are chosen precisely so these keep passing without edits: the whole bonus-assembly
block (~18 tests reconstructing the speed/efficiency/success sums term by term, including
`test_enhancing_special_case_tool_is_success_gloves_are_speed`'s exact
`efficiency == 0.0`), `test_points_formula`, the entire upgrade-probe block
(`test_probe_prices_a_single_level_bump_and_its_payback`,
`test_probe_finds_the_cheapest_bumping_level_like_a_brute_force_scan`, …), every parser
test in `test_signup.py`, and `test_scorer_cache_matches_fresh`'s `sim_calls == 1`
(partial progress adds **no** simulations).

### 7.2 Must be updated, with the new assertion

| test | change |
|---|---|
| `test_optimizer.py::test_scorer_total_matches_simulate_race_directly` | compare against `credit_points`; exact under `ρ = 0` |
| `::test_no_free_rider_left_behind` (×11) | terminal invariant `withm - base < 0` → `< -TRIAL_FILL_MAX_POINT_COST - EPS` |
| `::test_fill_bench_never_lowers_total_and_only_adds` | same, plus "never lowers by more than the subsidy" |
| `::test_refine_slack_preserves_points_and_never_lowers_the_worst_margin` | *"compared as exact ints"* → the tolerance; assert `min` strictly rises on every accepted move |
| `test_signup.py::test_safety_swaps_never_change_the_points` | "exactly equal" → "never costs more than `SIGNUP_SAFETY_POINTS_TOLERANCE`", asserted on **every prefix** as now |
| `::test_swaps_are_strictly_improving_and_consistent` | `reachable_total == enforced_total + Σ gain` → `pytest.approx` |
| `::test_weak_fill_that_lowers_points_is_not_seated` | `fill_gain >= 0` → `>= -TRIAL_FILL_MAX_POINT_COST` |
| `::test_compound_reshuffle_crosses_a_tier_plateau` | keep (its `FakeScorer` still guards the grouping code) but add a note that partial credit halves the plateau it defends, and add a real-model companion |
| `test_trials.py::test_guild_building_levels_all_zero_in_shipped_config` | add the shrine analogue — and note it will fail the day the officers build anything, exactly as this one will |

### 7.3 `_thin_scenario` must be re-searched — and made non-vacuous

`tests/test_signup.py:494`'s levels were *"FOUND BY SEARCH, not guessed"* to reproduce a
live 0.63%-margin shape in which phase 1 runs dry and only a volunteer override finishes
the job. Partial credit, the shrine terms and any headcount change all invalidate it.
Its consumers assert `len(free_only) >= 1`, `any(m.overrides_signup ...)` and
`len(full) > len(free_only)` — **which pass vacuously if the fixture stops producing
moves at all.** Two required actions:

1. Re-run the search that produced it and record the procedure in the test docstring so
   the next model change is a 10-minute job rather than an archaeology exercise.
2. Add an explicit non-vacuity assertion (`assert plan.safety_swaps`, with a message
   naming the fixture) so a silently empty list fails loudly. This is the guard that
   would have caught the §5.3 regression.

### 7.4 New tests

| # | test | pins |
|---|---|---|
| 1 | `ρ = 0.0` ⇒ `credit_points == float(points)` **exactly**, over a roster sweep, and `optimize()` returns **identical parties** to the pre-change golden | the one-line rollback is real, not aspirational |
| 2 | `tier_progress_fraction` ∈ [0,1); `= (B − τ)/ttc`; `0.0` on a zero-rate party; `0.0` when nothing failed; `0.0` on an empty party | §6.1 edge cases |
| 3 | `credit_points` is **monotone non-decreasing** in party throughput across a level sweep spanning ≥ 4 tier crossings | `_cheapest_bumping_level`'s binary search; "stronger is never worse" |
| 4 | crossing a tier boundary raises `credit_points` by ≥ `(1−ρ)·TRIAL_POINTS_PER_TIER` | the residual step is real |
| 5 | the degeneracy is gone: adding candidates of descending level gives strictly decreasing Δ with exactly one sign change | §2.3; the benching calculus |
| 6 | a thin fixture yields a **non-empty** safety-swap list | the §5.3 silent regression |
| 7 | a member below a trial's minimum level appears in **no** shipped party, in `trials.json` or `signup.json` | Phase 4 enforcement |
| 8 | `SHRINE_BUFFS_APPLY_IN_TRIALS = False` ⇒ rates bit-identical; the three non-race shrines never move a rate at any level | Phase 3 rollback |
| 9 | tolerance honoured: a move costing more than `*_POINTS_TOLERANCE` is refused; one costing less and lifting `min` is accepted | §5.3 |
| 10 | `credit_points` is deterministic across runs and independent of party iteration order | the ULP discipline of `_prepare_member` |

### 7.5 Live regression harness (not pytest)

Before/after on both live rosters at the same seed, recording: deterministic points,
credit points, per-trial `f`, party sizes, bench size and composition, minimum margin,
minimum `P(hold)`, safety-swap count, and wall-clock for the optimize step. §2.5 is the
"before" row; the plan is not done until the "after" row is written into
`research/partial-tier-credit.md`.

---

## 8. ⚠ Risks and mitigations

**Risk 1 — the safety-swap list silently empties.** `signup._safety_swaps`'s
`key[0] == base_points` is an exact equality on a value that becomes continuous. It will
match nothing, the list will be empty, the page will print *"None found"*, and **no test
will fail** (§7.3). *Mitigation:* the tolerance (§5.3) and new test 6, plus the
non-vacuity assertion. This is the single most likely way to ship a silent regression.

**Risk 2 — CI does not run the tests.** `deploy.yml` runs only `python -m src.build`.
Every guarantee in §7 is enforced only on a developer's laptop. *Mitigation:* Phase 0
adds a `pytest` job; additionally, assert in-build invariants (party sizes ≤ cap, no
ineligible member, `credit_points >= points`, totals finite) so the build itself fails
loudly on nonsense.

**Risk 3 — partial credit may not apply to guild points at all** (§3.1). *Mitigation:*
`TRIAL_PARTIAL_CREDIT_RATE = 0.0` ships in Phase 1; the flip is one line, after one
capture. Phases 3–5 are independent of the answer.

**Risk 4 — the headcount coefficient may have moved** (§3.3), which would change the
break-even and every numeric fixture. *Mitigation:* nothing in this plan hard-codes the
coefficient; §2.3's break-even is *derived* from
`HEADCOUNT_PENALTY_PER_MEMBER`. Verify from the refreshed dump before quoting "~1%" on
the page.

**Risk 5 — the bench grows and members are unhappy.** *Mitigation:* it does **not** grow
on today's live rosters — §2.5 measured the opposite, that every party would grow if the
cap allowed — which is worth saying out loud rather than shipping a scare. When marginal
value does start binding: `TRIAL_FILL_MAX_POINT_COST` makes inclusion a priced, visible
choice, and Phase 4's minimum-level recommendation gives officers a legitimate in-game
mechanism instead of a web page telling people to sit down.

**Risk 10 — the party cap is wrong, and now it matters** (§3.7). If the real cap is 20,
every tier and probability the site publishes is optimistic by four contributors per party.
*Mitigation:* Phase 5's marginal-seat line makes the sensitivity visible; the capture that
resolves it is one trial away; `TRIAL_PARTY_CAP` is already a single constant threaded
through `run_week` / `optimize` / `plan`, so correcting it is a one-line change with no
structural work.

**Risk 6 — float determinism.** `credit_points` is derived from `timeline` floats and
summed across trials. `trials._prepare_member` documents that a one-ULP change in a party
rate once *"kept its 4800 points but reshuffled every party for no gain"*.
*Mitigation:* keep the existing `sum()`-over-generator and factor-order discipline; do
not pre-multiply; new test 10; `OPT_POINTS_EPS` on every strict comparison.

**Risk 7 — shrine terms perturb every rate, breaking hand-computed fixtures and
`calibrate.selftest`'s `worst < 1e-9`.** *Mitigation:* separate `MemberBonuses` fields
(§5.1/Phase 3.3) keep the bonus tests exact; `calibrate._prepare_perturbed` and
`simulate_trial.py` are edited in the **same commit** as `member_bonuses`, never after.

**Risk 8 — runtime.** Partial credit adds zero simulations, but the re-founded
`_refine_slack` may iterate further and `_fill_bench` now discriminates. *Mitigation:*
`OPT_SLACK_MAX_ITERS` already bounds it; measure the optimize step per phase against the
~10-minute CI budget (`config.py:210-214`); the shipped `OPT_RESTARTS = 4` is the first
dial to trim if needed.

**Risk 9 — `_compound_reshuffle_into` may go quiet.** It exists because *"no single swap
crosses the line"*. With the plateau halved, single moves often suffice and the compound
path may never fire — harmless, but it would rot untested. *Mitigation:* keep the
`FakeScorer` test; assert in the live harness whether any reshuffle was emitted, and
record it.

### If implementation gets stuck

Ship Phase 1 and stop. Instrumented partial progress on the pages — *"tier 11, 23% into
tier 12"* — is a genuine improvement on its own, is provably behaviour-neutral, and puts
the number that decides §3.1 in front of the guild every day.

---

## 9. 🔄 Rollback

Every phase is one line or one revert.

| phase | rollback | effect |
|---|---|---|
| 2 (objective) | `TRIAL_PARTIAL_CREDIT_RATE = 0.0` | `credit_points == float(points)` bit for bit; every strategy's trajectory identical |
| 2 (safety) | `OPT_SLACK_POINTS_TOLERANCE = 0.0`, `SIGNUP_SAFETY_POINTS_TOLERANCE = 0.0` | the strongest guarantee a continuous objective allows |
| 2 (fills) | `TRIAL_FILL_MAX_POINT_COST = 0.0` | no subsidised seats |
| 2 (all of it) | `OPT_SLACK_PASS = False` | the existing pre-2026-07-31 lever, still works |
| 3 | `SHRINE_BUFFS_APPLY_IN_TRIALS = False` | rates bit-identical to Phase 2 |
| 4 | clear the sheet's min-level column | data-driven, so absence *is* the rollback |
| 5 | `git revert` | copy only |
| 1, 6, 7 | `git revert` | additive fields, unread by the pages |

No data migration and no schema removal: every JSON change is **additive**, and the pages
already follow the degrade-don't-fail rule `draw.py` established.

---

## 10. 📊 Success criteria

1. `TRIAL_PARTIAL_CREDIT_RATE = 0.0` reproduces today's site byte-for-byte apart from
   additive JSON keys. *(the rollback is real)*
2. With credit on, no deterministic-point regression on either live roster at the same
   seed, and the credit total ≥ §2.5's figures (4940.37 SC / 4626.82 LI).
3. Both pages state, per trial, how far into the next tier the party got and what that is
   worth.
4. `build.py:928-931`, `1871-1883` and `1901-1915` no longer assert things that are false.
5. The upgrades table prints a number for every drawn skill instead of *"No building can
   buy another tier this week, at any level"*, and prices shrines beside buildings with
   §2.6's verdict.
6. Every trial reports the minimum sign-up level that would reproduce the model's party,
   its marginal-seat sensitivity (§3.7), and no ineligible member is ever seated.
7. `pytest` runs in CI and is green; the suite gains tests 1–10 of §7.4; no test passes
   vacuously.
8. Optimize-step wall clock within +10% of today's ~42 s (SC) / ~36 s (LI).
9. `research/partial-tier-credit.md` carries the before/after live table and the resolved
   (or still-open, and labelled) status of every §3 question.

---

## 11. 🔗 References

* Patch notes — verbatim in `research/partial-tier-credit.md` (Phase 0).
* `research/risk-aware-objective.md` — §5 **R1** (the pre-written `float` migration this
  plan executes), §6 phasing, §8 verification plan, §9 rollback pattern. Note its own
  status warning: only Model 1 shipped.
* `research/trial-messages.md` — confirmed work/success formulas; `currentProgress` and
  `currentTrialsData` (the §2.7 verification kit); the headcount linear-vs-compounding
  question at 318-330; guild-building data at 103-152.
* `/Users/morgan/pie/farm/cowstuff/milkyway_client_info.json` — `guildBuffDetailMap`,
  `guildShrineDetailMap` (§2.1). **Pre-patch at time of writing.**
* `config.py:311-331` (`_refine_slack` rationale), `:395-417` (safety-swap rationale),
  `:466-505` (confirmed formulas), `:554-644` (guild buildings + cost curve).
* `optimizer.py:74-90` (`AssignmentScorer` contract), `:756-802` (`_fill_bench`),
  `:808-915` (`_refine_slack`).
* `signup.py:789-801` (`_slack_key`), `:804-1060` (`_safety_swaps` and the two acceptance
  conditions learned from a live probe).

---

## 12. 📊 Plan metadata

| | |
|---|---|
| Phases | 7 (0–6 planned, 7 optional) |
| Files | 2 new, 10 modified, 1 new test file |
| New config constants | 12 |
| Tests updated / added | ~9 updated, 10 added |
| One-line rollbacks | 6 |
| Blocking open questions | 2 (§3.1, §3.2); §3.7 blocks *publishing advice*, not the code |
| Measurements taken for this plan | 6 probes, 2 live rosters, 1 game-data dump |
| Ship-if-stuck point | end of Phase 1 |
