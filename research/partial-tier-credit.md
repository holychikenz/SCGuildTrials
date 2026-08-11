# Partial-tier credit: the patch that de-degenerated the trials objective

**Status**: the game patch of **2026-08-11** is CONFIRMED to exist and its
partial-credit wording is quoted verbatim in §1. **§3.1 of the implementation plan
— "does the credit land on guild points or only on loot?" — is RESOLVED (user,
2026-08-11): it lands on GUILD POINTS.** There is no separate loot table for guild
trials, so there is nowhere else for it to land, and
`config.TRIAL_PARTIAL_CREDIT_RATE` therefore ships at **0.5** rather than at the
`0.0` the plan hedged with. That resolution is the entire reason the objective
change is going ahead: it is what turns partial credit from a display curiosity
into the thing the optimizer maximises.

**Scope**: `src/config.py` (the constant and its rationale), `src/trials.py`
(`tier_progress_fraction`, `credit_tiers`, `points_for_result`, `credit_points`),
`src/optimizer.py` (`AssignmentScorer`, `_fill_bench`, `_refine_slack`),
`src/signup.py` (`_slack_key`, `_safety_swaps`, `_fill_open_seats`), `src/build.py`
(the copy that is now false). Combat is **out of scope everywhere** — see §1.

**Measurements**: every table in §3–§6 was taken for the implementation plan
(`.claude/plans/guild-trials-2026-08-patch-implementation-plan.md`, §2.2–§2.6) on
this repo's own model; §5 on the **live** Survey Corps (102) and Lactose
Intolerance (97) rosters on 2026-08-11, draw
`[Woodcutting, C.Smithing, Crafting, Cooking]`. They are reproduced here rather
than re-derived, so that the plan can be deleted and the numbers survive.

**Still open**: five questions, §7. The newly urgent one is **not** anything about
partial credit itself — it is `TRIAL_PARTY_CAP` (§7.5). Partial credit is what made
it *visible*.

**Line numbers** into `src/` were verified on 2026-08-11 against the tree that
carries Phase 1; they will drift, so the symbol names are the real citation.

---

## 1. The patch notes

**VERBATIM**, as relayed by the guild's officers on 2026-08-11. Reproduced first and
unedited, because everything downstream is a *reading* of these sentences and a
reading is only as good as the sentence it reads — §2's formula in particular is an
interpretation of Guild Trials item 4 and nothing else.

```text
Guild Trials
1) Base attack/cast speed and ability haste significantly reduced for bosses
2) Participant count now scales monster +2% attack/cast speed and +2 ability haste
3) Monster rebalance: Badger/Chameleon/Jellyfish HP & defenses up
4) Partial-tier progress is tracked when a trial ends, granting partial rewards. 0.5% credit per 1% progress. up to 50% credit at 99.99% but incomplete
5) New post-trial Stats modal with per-member combat/skilling stats
6) Leaders/generals can set a per-trial minimum signup level
7) Shrine buffs now apply inside guild Trials

Guild
1) Shrine buffs strengthened: Rare Find 1% → 1.5% per level, Essence Find 2% → 3% per level
2) New [View Buffs] button in the guild shop's Shrine Buffs section, showing your active
   guild buffs split into Skilling and Combat
3) Guild credit exchange reworked: the "Batches" input is replaced by two linked inputs
   (items to give / credits to receive)
4) Pinned message display improvement
```

### What each item means for this model

**Guild Trials**

1. **Boss haste.** **COMBAT — OUT OF SCOPE.** Recorded, modelled nowhere: this repo
   simulates only the four skilling trials (`research/trial-messages.md:222-235` —
   combat trials run through the battle engine on a `guild_battle_updated` channel
   and carry no work-value payload at all).
2. **Participant count → monster speed.** **COMBAT-WORDED — OUT OF SCOPE as
   written**, and the highest-value out-of-scope item in the patch. It is a rebalance
   of *how participant count is applied*, and participant count is the one term this
   repo models on both sides. See §7.2: if the skilling headcount penalty moved from
   1% to 2% per member, the break-even in §3 doubles and the benching picture in §5
   changes qualitatively.
3. **The Badger / Chameleon / Jellyfish rebalance.** **COMBAT — OUT OF SCOPE.**
4. **Partial-tier progress.** **This is the whole of §2**, and the sentence is
   transcribed into `config.TRIAL_PARTIAL_CREDIT_RATE`'s comment block. Note the
   notes' own punctuation — "granting partial rewards. 0.5% credit per 1% progress." —
   is what raised the question of whether the credit reached *guild points* at all;
   the Status block above records that it does.
5. **A post-trial Stats modal**, "with per-member combat/skilling stats". Potentially
   the first per-member ground truth this project has ever had — see §7.4.
6. **A per-trial minimum sign-up level.** A hard eligibility constraint the optimizer
   must respect — and, read the other way, the officers' only *mechanism* for actually
   carrying out a bench the model recommends. The data source is a design choice
   rather than a research question: a third column in the officers' `Trial Priority`
   table, which `draw._parse_priority_block` already walks.
7. **Shrine buffs now apply inside Trials.** Two of the five shrines carry *skilling*
   buffs that enter the race — Force → efficiency, Tempo → action speed. Full
   treatment, with the game-data table and both cost ladders, in
   **`research/guild-shrines.md`**.

**Guild**

1. **"Rare Find 1% → 1.5% per level, Essence Find 2% → 3% per level".** Worth more
   than its face value: it is the **cross-check that validates the entire shrine
   reading**, because the pre-patch dump holds `rare_find` at exactly `0.01/level` and
   `essence_find` at exactly `0.02/level`. It also tells us Force and Tempo were *not*
   re-tuned — only made applicable inside Trials. See `research/guild-shrines.md` §3.
2. **The `[View Buffs]` button**, splitting active guild buffs into Skilling and
   Combat. The intended resolution for §7.3: it displays exactly the resolved buff
   magnitudes the model needs and cannot currently see.
3. **The guild-credit exchange rework.** **OUT OF SCOPE**: no part of this model
   touches guild credits. Noted only because the *buff* cost ladder is priced in
   credits (`guild-shrines.md` §4), so a credit rework changes what a buff level
   *costs* without changing what it *does*.
4. **Pinned message display.** No modelling consequence.

---

## 2. The rule, reduced to a formula

`0.5% credit per 1% progress`, with `99.99% → ~50%`, is a **pure linear rule of
slope `0.5` with no separate cap**. The arithmetic settles it: `0.5 × 99.99% =
49.995% ≈ 50%`. The quoted *"up to 50% credit at 99.99%"* is therefore **the limit
of the linear rule, not a clamp bolted on top of it** — a distinction that matters,
because a genuine cap would put a second plateau back into the objective at
`f ≥ 1.0`, and there is no such plateau.

With `T` the highest tier cleared and `f` the fraction of the first *uncleared*
tier's work completed at the buzzer:

```
creditTiers = T + ρ·f            with ρ = TRIAL_PARTIAL_CREDIT_RATE = 0.5
points      = 0                              if creditTiers == 0
            = 100 + 100 · creditTiers        otherwise
```

**The shape of the objective, which is the point.** It is now **a ramp of height
`ρ·100 = 50` followed by a step of `(1−ρ)·100 = 50`** at each tier boundary. The
old 100-point cliff is **halved, not removed**, and both halves earn their keep:

* the **ramp** is what kills the degeneracy — every seat, every swap, every extra
  second of throughput now moves the score;
* the **residual step** is why `signup._compound_reshuffle_into` still has a job.
  It exists because *"no single swap crosses the line"*; with the plateau halved,
  single moves often suffice, but a 50-point discontinuity is still a
  discontinuity (see the plan's Risk 9 — the compound path may go quiet, which is
  harmless but would rot untested).

**`f` costs nothing.** It needs no new simulation and adds no `simulate_race`
call. `simulate_race` already records the failed tier in `timeline` with its
`time_to_clear`, and `tier_clear_seconds(result)` already reports the clock at the
last banked tier:

```
f = (BUDGET − tier_clear_seconds(result)) / failed_step.time_to_clear
```

`research/risk-aware-objective.md:63-77` had already named this exact quantity as
information *"already in the return value and being discarded by `.points`"*. That
note's §5 goes further and calls the smoothing a **"happy accident"**:

> *"smoothing the objective should make the existing search strictly better,
> because the plateaus that `marginal_greedy` and `hill_climb` currently grope
> across become slopes. A move that buys 40 seconds toward the next tier is
> currently invisible; under Model 2 it is a positive delta."*
> — `research/risk-aware-objective.md:376-379`

**The game has now done that smoothing for us**, which promotes that note's
pre-written migration **R1** (`float` points, tolerance comparisons, a colder SA —
lines 381-387) from an optional research direction to the required migration.

### 2.1 Two names, deliberately

`TrialResult.points` keeps its exact present meaning — integer, step function of
the cleared tier, the game's confirmed-shape award — and a **new**
`credit_points: float` carries the partial-credit score. At
`TRIAL_PARTIAL_CREDIT_RATE = 0.0` the two are bit-identical, which is what makes
the whole objective change a **one-line rollback** (`config.py:564-567`) rather
than a revert, and what keeps ~60 existing tests untouched. Note the shipped
constant for the second, unconfirmed half of the rule is
`TRIAL_PARTIAL_CREDIT_BASE_ON_PARTIAL` (`config.py:583`); the plan calls it
`TRIAL_PARTIAL_CREDIT_BASE_PRORATED`. Same question (§7.1), different name.

---

## 3. Measured: the degeneracy, and where the break-even sits

**Fixture.** A synthetic **20-strong Foraging party**, member levels spanning
**130 down to 88**, on shipped config: `TRIAL_TIME_BUDGET_SECONDS = 3600`,
`TIER_TARGET_PER_LEVEL = 400`, `HEADCOUNT_PENALTY_PER_MEMBER = 0.01`,
`GUILD_BUILDING_LEVELS` all zero, community buffs dormant, no shrine terms. It
reaches **tier 11** with a **10.3% margin** (≈ 372 s of 3600) and **`f = 0.228`**,
i.e. `old = 1200`, `credit = 100 + 100·(11 + 0.5·0.228) = 1211.40`. One extra
member is then added at a range of levels; `old Δ` is today's objective, `new Δ`
is partial credit.

> **Reproduction gap, flagged rather than papered over**: the plan records the
> level *range* (130…88) but not the exact 20-vector, and no seed (the fixture is
> deterministic, so a seed is not needed for the race — but it is needed for
> anything that goes through `optimize`). Record the vector in the probe's
> docstring when it is next run; the numbers below cannot otherwise be reproduced
> to the second decimal.

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

Two facts, both load-bearing:

* **Every** candidate from level 140 down to level 10 scores `Δ = 0` today. The
  degeneracy is **total** — a level-140 whale and a level-10 tourist are the same
  zero — and it is exactly why `optimizer._fill_bench` could justify itself as
  *"a member who crosses no threshold contributes exactly zero — no harm done"*
  (`optimizer.py:762-764`). Under partial credit that sentence is false, and the
  pass needs a policy instead of an alibi (`TRIAL_FILL_MAX_POINT_COST`,
  `config.py:597-609`).
* Under partial credit the sign changes between a rate share of **1.1% and 1.0%**.
  That matches the theoretical break-even `1/(100 + N) = 1/120 = 0.83%`, inflated
  by the fact that an extra head raises the effective target of *every* tier
  including the partial one. **A member earns their seat iff they contribute more
  than about 1% of the party's throughput at the contested tier** — which is
  precisely the consequence `research/trial-messages.md:318-330` wrote down as a
  WORKING ASSUMPTION in July (*"weak stragglers can now actively lower the tier
  reached"*) and could never act on, because under a step objective the model
  could not see it.

---

## 4. Measured: monotonicity, and the margin↔credit identity

**Fixture**: the §3 party, unchanged, with the whole party's levels shifted by a
common offset.

| shift | tier | `f` | credit points |
|---|---|---|---|
| −40 | 7 | 0.090 | 804.48 |
| −35 | 7 | 0.576 | 828.80 |
| −30 | 8 | 0.130 | 906.50 |
| ±0 | 11 | 0.228 | 1211.40 |
| +15 | 12 | 0.770 | 1338.50 |
| +30 | 14 | 0.085 | 1504.26 |

**`credit_points` is monotone non-decreasing in party throughput** across the
whole sweep, *including at every tier crossing* — because banking a tier gains
`100` while surrendering at most `ρ·100 = 50` of accumulated partial credit. Note
the `−35 → −30` row pair, which is the crossing that could have broken it: `f`
falls from 0.576 to 0.130 and the score still rises, 828.80 → 906.50.

This is not cosmetic. It is the **precondition** for the binary search in
`trials._cheapest_bumping_level` and for the "a stronger party never scores less"
invariants in the test suite, and the plan pins it as new test 3 (§7.4).

**Fixture**: the same party, shrunk one member at a time (weakest first).

| N | tier | margin | `f` | old | credit |
|---|---|---|---|---|---|
| 20 | 11 | 0.1033 | 0.228 | 1200 | 1211.40 |
| 17 | 11 | 0.0723 | 0.150 | 1200 | 1207.52 |
| 14 | 11 | **0.0162** | 0.031 | **1200** | 1201.56 |
| 13 | 10 | 0.2836 | 0.963 | 1100 | 1148.13 |

Because `f = 3600·margin / ttc(T+1)`, **partial credit is a linear read-out of the
very time margin `optimizer._refine_slack` was invented to protect**. At N=14 the
lineup holds tier 11 by **1.6% — 58 seconds** — and scores *identically* to the
comfortable N=20 lineup under today's objective; under partial credit the
comfortable one is worth 9.8 points more. **The new objective walks off the buzzer
by itself.**

What it does **not** do is protect the *thinnest* trial, because the objective is
a **sum** and risk is a **minimum**. That asymmetry is the residual job left to
the safety passes, and it is why the page copy at `build.py:1871` — *"The margin
is the risk. Points are a step function of the tier reached…"* — must be rewritten
rather than deleted: the first sentence survives, the reason given for it does not.

---

## 5. Measured on the LIVE rosters (2026-08-11)

**Fixture.** Shipped optimizer, `TRIAL_PARTY_CAP = 24`, live rosters as read from
the guild sheet on 2026-08-11: **Survey Corps 102 members, Lactose Intolerance
97**. Draw `[Woodcutting, C.Smithing, Crafting, Cooking]` — four *production*
skills, where the roster is deep. Seed **not recorded in the plan**; it must be
recorded for both rows of §9, since the plan's own success criterion is "no
deterministic-point regression at the same seed".

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

(The credit column sums to 4940.36 / 4626.81 from the *rounded* per-trial figures;
the totals as given are the unrounded ones. Quoted as measured.)

**A result that inverts the obvious expectation, and redirects the whole plan.** A
greedy trim — repeatedly drop whichever member most *raises* credit points —
removes **nobody**, on all eight parties, on both guilds. Probing the other
direction says why:

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

Every seated member clears the break-even, and **every benched member would raise
credit points if the cap allowed it**. The bench today is produced entirely by
`TRIAL_PARTY_CAP = 24` (4 × 24 = 96 seats against 102 and 97 members) — a constant
whose own comment calls it *"a magic number"* (`config.py:197-198`) — and **not**
by marginal value. Nobody deserves benching; the parties want to be *bigger*.
That is the finding that promotes §7.5 from a footnote to the urgent question.

**What the patch is worth, on today's assignment**: **+40.4 points (0.8%) to SC**
and **+126.8 (2.8%) to LI**. LI gains three times as much because its parties sit
mid-ramp (`f ≈ 0.59–0.76`) — i.e. the guild has been earning most of another
tier's worth of credit every week and seeing none of it. SC's parties bank their
tier and then sit near the *bottom* of the next ramp (`f ≈ 0.12–0.25`), so it has
less unbanked progress to be paid for.

---

## 6. Measured: what a shrine buys, and what it costs

Recorded here because the probe shares §3's fixture; the game data, the two cost
ladders and the full ten-buff table live in **`research/guild-shrines.md`**.

**Fixture**: the §3 synthetic Foraging party, applying Force (efficiency) and/or
Tempo (action speed) at `0.005/level`, priced against the **shrine** guild-point
ladder at `TRIAL_WEEKS_BETWEEN_DRAWS = 2.5` weeks between draws
(`config.py:759`). "Weeks to repay" is the cumulative guild-point cost divided by
the per-draw credit gain, times 2.5.

| shrine level | `f` | credit points | Δ | cumulative gp | weeks to repay |
|---|---|---|---|---|---|
| none (today, ignoring the live L1s) | 0.228 | 1211.40 | — | — | — |
| L1 Force | 0.235 | 1211.75 | +0.35 | 1 000 | 7 196 |
| L1 Force + L1 Tempo | 0.240 | 1212.01 | +0.61 | 2 000 | 8 233 |
| L5 both | 0.293 | 1214.67 | +3.27 | 19 800 | 15 152 |
| L20 both | 0.493 | 1224.64 | +13.24 | 2 304 200 | 435 239 |

**Two conclusions, and the second is the useful one.** (a) The buffs are **real
and must be modelled** — Force+Tempo at L1 is +0.61 points per trial *today*, and
Survey Corps holds both at level 1, so the model is currently wrong by that much
(`research/trial-messages.md:154-160`). (b) As an **investment** they are
catastrophic: even fully maxed, Force+Tempo buys **less than one tier** for 2.3M
guild points, on a cost ladder that is exactly **twice** the buildings'. The
trials page should price shrines *and say plainly that buildings dominate* — a
negative result the guild can act on, and one nobody can currently see.

---

## 7. Open questions, each with its resolution recipe

§3.1 of the plan (does the credit land on guild points?) is **CLOSED** — see the
Status block. §3.5 (where the minimum sign-up level comes from as data) is a
design choice, not a research question. What remains:

### 7.1 Is `ρ` exactly `0.5`, and is the `100`-point base also pro-rated? (plan §3.2)

Two sub-questions. **(a)** `0.5` is stated in the note and is assumed exact; there
is no reason to doubt it, and the whole model is linear in it. **(b)** is the real
one: `points_for_tier` awards a flat `100` *"for finishing at all"*
(`config.py:511-518`, itself an ASSUMPTION fitted to exactly two observations —
milking tier1 → 200, tier2 → 300). Does a party at 99% of tier 1 receive `0`,
`50`, or `150`?

The shipped reading is *"credit is on the per-tier term; the base is awarded iff a
tier is actually banked"*, behind `TRIAL_PARTIAL_CREDIT_BASE_ON_PARTIAL = False`
(`config.py:569-583`), because it is the only reading consistent with the existing
`points(0) == 0` — and because the model's standing rule is to understate an
unconfirmed gain.

**Resolution**: the §8 capture, on any trial that fails tier 1 — or the new
per-member Stats modal. Note this edge case **cannot arise on a real lineup**:
every live party reaches tier 10–12. It exists so that tiny and empty parties are
scored coherently, which is why it is not blocking.

### 7.2 Did the *skilling* headcount penalty change? (plan §3.3) — HIGH VALUE

Guild Trials item 2 (§1) — *"Participant count now scales monster +2%
attack/cast speed and +2 ability haste"* — is combat-worded, but it is a
**rebalance of how participant count is applied**, and
`HEADCOUNT_PENALTY_PER_MEMBER = 0.01` (`config.py:528-530`) is the entire basis of
the break-even in §3 and §5. At 1%/head the break-even is ~1% of party
throughput; **at 2% it doubles**, and the "nobody deserves benching" conclusion of
§5 — where the weakest seated shares run 1.03%–3.77% against a 0.81% break-even —
would flip for several parties at once.

Note the repo *also* still carries the unresolved linear-vs-compounding question:
`(1 + N/100)` vs `1.01^N`, which differ by 1.20 vs 1.22 at N=20
(`research/trial-messages.md:318-322`).

**Resolution**: the refreshed client dump (Phase 0 step 1), then a
`targetWorkValue` capture at two different party sizes — which settles the
coefficient *and* the linear-vs-compounding reading in one go. **Do not quote
"~1%" on the page until this is done**; nothing in the code hard-codes it (the
break-even is derived from the constant), so the exposure is entirely in the copy.

### 7.3 Which shrine ladder drives the multiplier, and what are the live levels? (plan §3.4) — HIGH VALUE

The shrine **level** (priced in guild points) and the buff **level** (priced in
guild tokens + guild credits) are **two separate ladders** — see
`research/guild-shrines.md` §4. The capture gives the *shrine* level (Force 1,
Tempo 1, `research/trial-messages.md:154-160`); the *buff* level is not in any
capture this repo holds.

**Resolution**: the new `[View Buffs]` button (Guild item 2), which the notes say
splits active guild buffs into Skilling and Combat — i.e. it displays exactly the
resolved magnitudes the model needs. Until then `GUILD_SHRINE_LEVELS` is a
hand-entered config map carrying the same caveat `config.py` already carries for
`GUILD_BUILDING_LEVELS`: one map serves both guilds, and it must be split the
moment SC and LI diverge.

### 7.4 Does the new Stats modal expose per-member contribution? (plan §3.6) — OPPORTUNITY, not a gate

*"per-member combat/skilling stats"* would be the **first per-member ground truth
this project has ever had**, and `src/calibrate.py` is built to consume exactly
that. Its `RISK_SIGMA_SYSTEMATIC = 0.0131` (`config.py:406`) exists *because*
neck/ring/earring gear and real enhancement levels are unobserved: a modal that
reports per-member work would let that constant be **measured instead of
inferred**.

**Resolution**: a research note of its own plus a scraper task in the sibling
Tampermonkey repo. Explicitly **out of scope** for the partial-credit work.

### 7.5 Is the party cap real, and is it 20 or 24? (plan §3.7) — **NEWLY URGENT, and it cuts both ways**

**This is the question partial credit has just made answerable, and the most
consequential open item in this note.** The evidence is contradictory:

| source | says |
|---|---|
| `config.py:197-198` | `TRIAL_PARTY_CAP = 24`, flagged in its own comment as *"a magic number; a later change will read it from the guild spreadsheet"* |
| `research/trial-tabs.md:76` | *"max observed 20 for skilling, matching the 20-player cap"* — from the officers' own results log |
| `research/trial-messages.md:267-270` | the 20-cap *"is never observed directly… not stated in any captured message"* (the capture is single-character) |
| §5 above | all **eight** live parties sit **exactly on 24** and **every one of them would grow if allowed** |

So the constant is a **first-order source of error, in whichever direction it is
wrong**:

* **If the real cap is 20**, the model seats 24 where only 20 can play, and every
  published tier, margin and probability on both pages is **optimistic** — four
  phantom contributors per party, on parties whose margins run 8–29%.
* **If there is no cap at 24**, the guild is leaving roughly **5–8 credit points a
  week** on the table (§5's "uncapped growth" column, ×4 trials, ×2 guilds) and
  the tool is quietly telling it to.

Under the old step objective this question was *unanswerable and cost nothing* —
a marginal seat was worth exactly zero either way. It is now worth **1.2–2.2
points per seat, measurably**.

**Resolution**: one party capture from a trial the guild deliberately over-fills,
or the participant counts in the new post-trial Stats modal. Cheap, and it should
be settled **before the new numbers are published as advice**. Until then the page
should publish the exposure rather than hide it — a per-trial **marginal-seat
line**: *"weakest seated member contributes 1.03% against a 0.81% break-even; one
more seat would be worth +2.2 points"*, which states the sensitivity without
pretending to resolve it. `TRIAL_PARTY_CAP` is already a single constant threaded
through `run_week` / `optimize` / `plan`, so correcting it is a one-line change.

---

## 8. The verification kit we already have

`research/trial-messages.md:75-101` records `currentTrialsData` carrying, per
trial, `points` (the guild's *actual* award), `highestTier`, `budgetRemainingMs`
and `tierStartedAtMs`. **That is a complete verification kit for §7.1 and for the
resolved §3.1, with no new tooling:**

1. **Does the credit land on guild points, and is `ρ = 0.5`?**
   Any excess of `points` over `100 + 100 × highestTier` **is** the partial credit.
   The user has resolved the *whether* (Status block); the capture now measures the
   *how much*, and a single trial pins `ρ` to two decimal places:

   ```
   ρ̂ = (points − 100 − 100·highestTier) / (100 · f_observed)
   ```

2. **Is the model's `f` right?** `tierStartedAtMs` + `budgetRemainingMs` gives the
   progress fraction *in time* — the party started the failed tier at
   `tierStartedAtMs` and had `budgetRemainingMs` left of its hour — against which
   the model's `ttc(T+1)` can be checked directly, without any per-member data.

3. **Is the base pro-rated (§7.1b)?** Only a trial that fails tier 1 answers it,
   and none is expected. Record the check anyway; it costs a line.

The one thing the kit does *not* give is per-member contribution — see §7.4.

---

## 9. Live before/after

**Phase 6 completes this section.** The "before" row is §5, restated in the shape
the plan's live regression harness demands (§7.5 of the plan): both live rosters,
same seed, same draw. *The plan is not done until the "after" row is written
here.*

### Before — shipped optimizer, step objective, `cap = 24`, 2026-08-11

| quantity | SC (102 members) | LI (97 members) |
|---|---|---|
| draw | Woodcutting, C.Smithing, Crafting, Cooking | (same) |
| seed | **not recorded — record it in both rows** | **not recorded** |
| deterministic points | **4900** | **4500** |
| credit points | **4940.37** | **4626.82** |
| tiers | 11, 11, 11, 12 | 10, 10, 10, 11 |
| per-trial `f` | 0.248, 0.219, 0.221, 0.120 | 0.590, 0.675, 0.760, 0.511 |
| party sizes | 24, 24, 24, 24 | 24, 24, 24, 24 |
| bench size | 6 | 1 |
| bench composition | not recorded | not recorded |
| minimum margin | 0.0812 (Cooking) | 0.2409 (Cooking) |
| minimum P(tier holds) | not recorded | not recorded |
| safety-swap count | not recorded | not recorded |
| reshuffles emitted | not recorded | not recorded |
| optimize wall-clock | ~42 s | ~36 s |
| greedy trim | removes **nobody** | removes **nobody** |
| weakest seated share | 1.42% – 3.61% | 1.03% – 3.77% |

Wall-clock figures are the plan's stated baseline (§10, criterion 8); everything
else is §5 above. The blanks are not oversights to be tidied away — they are
quantities the "before" probe did not capture, and the "after" run must capture
**both** columns for them or the comparison is not a comparison.

### After — partial credit on (`ρ = 0.5`) + shrine buffs, shipped strategy `best`

Measured 2026-08-11 on the same draw and rosters, shipped config
(`OPT_RESTARTS = 4` of `beam+genetic+hill_climb`, seeds 1235–1238).

| quantity | SC (102) | LI (97) |
|---|---|---|
| draw | Woodcutting, C.Smithing, Crafting, Cooking | (same) |
| seed | 1234 (+1..4 derived) | (same) |
| **deterministic points** | **4900** (unchanged) | **4700** (+200) |
| **credit points** | **4971.43** (+31.06) | **4754.52** (+127.70) |
| tiers | 11, 11, 11, **12** | 10, **11**, **11**, **11** |
| per-trial `f` | 0.322, 0.591, 0.514, 0.001 | 0.835, 0.001, 0.001, 0.254 |
| party sizes | 24, 24, 24, 24 | 24, 24, 24, 24 |
| bench size | 6 | 1 |
| **minimum margin** | **0.0009** (Cooking, 3.2 s) | **0.0004** (C.Smithing, 1.4 s) |
| **minimum P(tier holds)** | **0.5183** | **0.5080** |
| optimize wall-clock | 62.7 s | 83.7 s |
| min-level advice | 102 / 111 / 108 / 118 | 103 / 103 / 103 / 111 |

Acceptance against the plan's criteria: deterministic points did not regress (SC
level, LI **+200**); credit points cleared both floors; the safety-swap list is
non-empty on the thin fixture and guarded by a test that fails when it is not.
Wall-clock did **not** hold — +49% on SC and +133% on LI against a stated +10%
budget — of which more below. Both still sit far inside the ~10-minute CI budget.

### 9.1 The result the plan got backwards

**§4 of this note claimed "the new objective walks off the buzzer by itself". That
is wrong, and the live run is the refutation.** The minimum margin did not improve
from 8.1% / 24.1%; it **collapsed to 0.09% and 0.04%** — three of the eight trials
now bank their tier with between one and four seconds to spare, at a
`P(tier holds)` of 0.51.

The reasoning error is worth stating precisely, because the *first* half of it is
sound. Within a tier, partial credit does price the margin linearly, so among
lineups that reach the same tier the search now prefers the roomier one — that part
holds. What it ignores is that the **residual step at the boundary is still worth
`(1 − ρ)·100 = 50 points**, which dominates any margin the search could buy by
staying put. So the objective does not walk off the buzzer; it walks off *this*
tier's buzzer and straight onto the *next* one. Every extra tier it found is,
almost by construction, held by seconds.

And the safety pass cannot undo it: `OPT_SLACK_POINTS_TOLERANCE = 0.0` forbids
surrendering any points at all, and stepping back from a knife-edge tier 11 to a
comfortable tier 10 costs ~55 points. So the pass correctly reports that nothing
helps.

**Is the gamble bad?** No — and this is the part that stops it being a regression.
Falling short of tier 11 does not lose the tier; it lands on tier 10 with ~99%
partial credit, i.e. ~1145 rather than ~1200. Taking LI's C.Smithing at
`P = 0.508`:

```
E[credit] ~ 0.508 x 1200 + 0.492 x 1145  ~  1173
safe alternative (comfortable tier 10)   ~  1145
```

so the risky lineup is genuinely better in expectation, by roughly 28 points. The
patch has made the downside of over-reaching *shallow* — that is precisely what
partial credit is for — and the optimizer is right to reach.

**What IS wrong is the published number.** The page prints 1200.03 for a lineup
whose expectation is ~1173, and it prints it beside a margin band that will read
knife-edge on three trials out of eight. Two consequences, both for Phase 5 and
beyond:

1. **The copy must change its stance.** The margin narrative was written when the
   optimizer guaranteed ~17% and a thin margin therefore meant something had gone
   wrong. A thin margin is now the *expected* outcome of a correct decision, and
   the page has to say so, or every officer reading it will conclude the tool has
   broken.
2. **`E[points]` is promoted from optional to necessary.** Plan §Phase 7 recorded
   it as "cheap and well-posed, but not to ship with the rest". This measurement is
   the argument for shipping it: the deterministic credit is now a systematically
   optimistic point estimate, over-claiming by ~27 points on one trial alone, and
   the machinery to correct it (`clear_sigma`, `RISK_SIGMA_SYSTEMATIC`, the
   timeline already in hand) is calibrated and waiting. It would not change which
   lineup the optimizer picks — the gamble survives an expectation test — but it
   would make the number the guild plans against the right one.

### 9.2 Wall-clock

+49% (SC) and +133% (LI) against the plan's +10%. The cause is not extra
simulations per race — partial credit is read off the timeline the race already
built, and `sim_calls` is unchanged — but a more informative surface: with the
plateaus gone the local search finds improving moves where it previously found
none, so it takes more accepted moves before it settles, each with fresh cache
misses. That is the *mechanism of the +200 points*, so it is a cost worth paying
rather than a regression to chase; `OPT_RESTARTS` is the dial if it ever matters,
and both guilds remain minutes inside the CI budget.

## 10. TODO

- [ ] **Paste the verbatim patch notes** over §1's paraphrases (Guild Trials 1, 3,
      5, 6, 7; Guild 2, 3; and the missing Guild item 4).
- [ ] **Refresh `/Users/morgan/pie/cowstuff/milkyway_client_info.json`** past
      `v1.20260715.0` and re-run the searches: `grep -c partial` was **0** on the
      pre-patch dump (re-verified 2026-08-11), so a non-zero count is itself the
      finding. Diff `guildBuffDetailMap`, `guildShrineDetailMap` and
      `guildTrialDetailMap`, and look for a participant-count term (§7.2).
- [ ] **Record the §3 fixture's exact 20-level vector** and the §5 seed.
- [ ] **Take the §8 capture** after the next trial: `points` vs
      `100 + 100 × highestTier`, and `tierStartedAtMs` / `budgetRemainingMs`
      against the model's `f`.
- [ ] **Settle the cap** (§7.5) before the new numbers are published as advice.
- [ ] **Fill §9's "after" row** — the plan is not complete without it.
