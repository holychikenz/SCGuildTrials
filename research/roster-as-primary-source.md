# Roster tabs as the primary member-data source — measurements

Companion to `.claude/plans/roster-as-primary-source-implementation-plan.md`.
This file records what was **measured**, phase by phase. Claims here are
observations; the reasoning lives in the plan.

## 1. BEFORE — the R0 baseline manifest

Taken on an unmodified tree at `afe14c5` (`profiles-endpoint`), full live build,
`uv run --no-dev python -m src.build`, exit 0. Test suite green at 259 passed.
Draw: **C.Smithing, Milking, Enhancing, Tailoring**. Seed 42, strategy `best`,
community buff level 1, guild shrines modelled as `force 1, tempo 1` for BOTH
guilds.

Artefacts: `/tmp/R0-{sc,li}-{trials,signup}.json`, a full `_site/` snapshot at
`/tmp/R0-site`, log at `/tmp/roster-R0-build.log`, SHA at `/tmp/R0-baseline-sha`.

### SC — `trials.json` (unconstrained optimum)

| trial | party | tier | partial | points | credit | E[points] | P(holds) |
|---|---|---|---|---|---|---|---|
| C.Smithing | 28 | 12 | 0.0574 | 1300 | 1302.9 | 1301.0 | 0.9584 |
| Milking | 24 | 12 | 0.1115 | 1300 | 1305.6 | 1305.4 | 0.9952 |
| Enhancing | 28 | 10 | 0.0543 | 1100 | 1102.7 | 1100.3 | 0.9485 |
| Tailoring | 27 | 11 | 0.0807 | 1200 | 1204.0 | 1203.6 | 0.9926 |
| **total** | | | | **4900** | **4915.2** | **4910.4** | |

seed `42`, cap 28, members 107, strategy `best`, buff level 1, shrines {'force': 1, 'tempo': 1, 'rarity': 0, 'spirit': 0, 'scholar': 0}

signup.json: keys ['budget_seconds', 'cap', 'enforced_credit_total', 'enforced_expected_total', 'enforced_step_total', 'enforced_total', 'gap', 'generated_at', 'min_slack_fraction', 'optimal_credit_total', 'optimal_expected_total', 'optimal_step_total', 'optimal_total', 'reachable_total', 'roster_count', 'safety_min_probability', 'safety_min_slack', 'signup_count', 'target_scale', 'week_date']

### LI — `trials.json` (unconstrained optimum)

| trial | party | tier | partial | points | credit | E[points] | P(holds) |
|---|---|---|---|---|---|---|---|
| C.Smithing | 25 | 11 | 0.0725 | 1200 | 1203.6 | 1203.1 | 0.9872 |
| Milking | 24 | 11 | 0.1846 | 1200 | 1209.2 | 1209.2 | 1.0000 |
| Enhancing | 26 | 9 | 0.0904 | 1000 | 1004.5 | 1004.2 | 0.9934 |
| Tailoring | 26 | 11 | 0.0002 | 1200 | 1200.0 | 1175.7 | 0.5031 |
| **total** | | | | **4600** | **4617.4** | **4592.3** | |

seed `42`, cap 26, members 101, strategy `best`, buff level 1, shrines {'force': 1, 'tempo': 1, 'rarity': 0, 'spirit': 0, 'scholar': 0}

signup.json: keys ['budget_seconds', 'cap', 'enforced_credit_total', 'enforced_expected_total', 'enforced_step_total', 'enforced_total', 'gap', 'generated_at', 'min_slack_fraction', 'optimal_credit_total', 'optimal_expected_total', 'optimal_step_total', 'optimal_total', 'reachable_total', 'roster_count', 'safety_min_probability', 'safety_min_slack', 'signup_count', 'target_scale', 'week_date']

### Two features of the baseline worth carrying forward

**LI Tailoring banks tier 11 on a coin flip.** `partial_fraction` 0.0002 —
two ten-thousandths past the boundary — at `P(holds) = 0.5031`. It is the exact
pathology `README.md` describes the E[points] objective as having been adopted to
prevent, and it survives here because the *deterministic* tier is genuinely
reached; the expectation prices it at 1175.7 against a step value of 1200. Under
the corrected model (§2.3 of the plan predicts LI +6.00%) this trial should clear
its tier with room to spare. **If it does not, something is wrong.**

**The build already reports the join problem this change exists to fix.** R0's own
log carries, unprompted:

```
NOTE (sc): 6 sign-up name(s) matched a member only after case/space normalisation
NOTE (li): 5 sign-up name(s) matched a member only after case/space normalisation
WARNING (li): 5 sign-up name(s) match NO member on the 'LI Member Data' tab and
              were IGNORED: IronPugs, U3, auuughhh, yiyaa, yiyya
```

Those five ignored names are **exactly** the five roster-only members the
ResearchPack found (§3). They are not typos: they are real characters who signed
up for this week's trials, exist on the LI Roster tab with full levels, houses,
shrines and tools — and are dropped, because the hand-maintained tab has never
heard of them.

**RESOLVED in R2, against the plan's first answer.** `ROSTER_ADMITS_NEW_MEMBERS`
ships `True`. The plan's §5.6 justification for dropping them rested on the
`yiyaa`/`yiyya` pair being one renamed character; measured on the live tab they
are two, with distinct `characterId`s (287196 / 287200) and different stats, and
`apps-script/profiles/Code.gs` upserts on `characterId`, so two rows can only
mean two characters. Both guilds also turn out to seat every member they have —
SC 28+24+28+27 = 107, LI 25+24+26+26 = 101, i.e. the whole roster each — so these
five are the only additional capacity in existence, not a change to who is
benched.

## 1.5 R1-R4 — what was measured while the master switch stayed OFF

Phases R1-R4 land the whole mechanism dark: `ROSTER_SOURCE_ENABLED = False`, so
no published number has moved. Everything below is either a rollback proof or a
measurement taken by running the merge live and throwing the result away.

**The rollback is proved twice, not asserted.** A full live build at R2 produced
`_site/` byte-identical to `/tmp/R0-site` — the only differences in the whole
tree were the embedded generation timestamps. Offline,
`test_roster_disabled_reproduces_the_golden_week` compares a thirty-member
synthetic week against `tests/golden/week_pre_roster.json`, which was generated
by running the same fixture inside a git worktree of the pre-change commit
`265326b`, so it compares against the OLD code rather than against itself.

**The join, live.** Exactly the ResearchPack's figures, re-measured through the
shipped code: SC 107/107 matched (6 recovered by case-insensitivity alone), LI
100/101, with `OTZ` the one LI member the roster has never seen. 9 SC and 7 LI
members hide their gear — all twenty tool columns blank, levels, houses and
shrines fully populated — which is the case the per-field precedence exists for.

**Roster-only members: five, and all real.** `IronPugs` (characterId 280884),
`U3` (281111), `auuughhh` (117231), `yiyaa` (287196), `yiyya` (287200). All 105
LI roster ids are distinct. See §1's RESOLVED note: they are now admitted.

**Shrines, re-measured through the merge.** Mean purchased force level 2.99 (SC)
and 2.30 (LI), against the 1.0 the model holds for everybody — matching the
ResearchPack exactly.

**The tool audit found nothing to warn about.** Zero unmodelled items and zero
named-tool-with-blank-enhancement observations on either guild, out of 980 roster
tool observations each. `config.TOOL_ENHANCE_WHEN_UNKNOWN` is therefore currently
never exercised on live data, and plan §11.6's "resolve before R5 if it exceeds
5%" trigger is not met at 0.0%. The 27 SC and 21 LI blank enhancement cells are
all attached to blank tool cells — the gear-hiders — so they never reach the
pricing path at all.

**The tool table reproduces the four shipped constants exactly.** `==`, not
`approx`, at `+7`, for Holy/Celestial Brush and Holy/Celestial Enhancer. That
required rounding the `(base, per)` pairs to 12 decimal places, which recovers
the catalogue's intended decimals from upstream float noise
(`0.0007199999999999999` → `0.00072`); the multiplier curve itself is transcribed
verbatim, because `calibrate._load_multiplier_table` reads the same array from
the same file.

**One plan claim is wrong, and it is a cost.** Plan §7.5 and Risk 9 state "ZERO
added work inside `_prepare_member` or `simulate_race`". Removing
`simulate_race`'s once-per-race shrine hoist costs about **+9%** on the race
itself — measured on a live 26-member LI party, 0.21 ms/race hoisted against
0.23 ms/race per-member, 300 races each. Small, worth the correctness, and not
zero. R5's timing check should expect it rather than treat it as a regression.

**R4 changes the artefacts without changing a number.** A second full build, still
with the switch off, differs from R0 in exactly three ways: four additive keys per
roster entry (`source`, `tool_source`, `tool_item`, `tool_enhance`), one
`provenance` block per artefact, and the new page furniture (the Member-data
strip, the per-member source marks, the tool badge, the three re-worded caveats).
Every number in `trials.json`, `signup.json` and `data.json` on both guilds is
identical once those keys are stripped, and all 107 SC source marks render hollow.

## 2. R5 — the flip, measured

Seven builds at seed 42, one switch at a time, all `rc=0`. Inputs frozen and
verified: the four source tabs were byte-identical before and after the whole
sequence, so nothing below is contaminated by an officer's edit mid-run. (They were
not always: between R0 and R5 the SC tab gained six edited cells, one of them
Tiberius's Tailoring level 110 → 111. It changed no output at all.)

### 2.1 Reconciliation — the verification

Mean Δrate over matched member × **drawn** skill (C.Smithing, Milking, Enhancing,
Tailoring), bands re-derived for this draw *before* the builds. "band" is a
hand-rolled mirror of the rate model that does not import `src.roster`; "impl" is
`roster.merge` + `trials._prepare_member`. Two independent code paths.

| slice | SC band | SC impl | LI band | LI impl | verdict |
|---|---|---|---|---|---|
| 1 levels | +2.539% | +2.539% | +6.713% | +6.713% | PASS |
| 2 houses | +0.035% | +0.035% | −0.120% | −0.120% | PASS |
| 3 shrines | +1.444% | +1.444% | +0.954% | +0.954% | PASS |
| 4 tools | **−0.211%** | **−0.211%** | **−0.872%** | **−0.872%** | PASS |
| all | +3.867% | +3.867% | +6.680% | +6.680% | PASS |

Agreement to **0.000pp** on every slice against a ±0.1pp tolerance. Interaction
residual +0.060pp (SC), +0.005pp (LI). **Slice 4 is negative on both guilds**, which
is the property that distinguishes four separate corrections from a uniform coat of
optimism.

Note the drawn-four bands differ from §5's all-ten figures (−0.52%/−1.26%) because
the draw includes Enhancing, where the tool feeds the success channel rather than
speed. The sign, which is what is load-bearing, is unchanged.

### 2.2 The manifest

| run | SC E[pts] | SC tiers | SC min P | LI E[pts] | LI tiers | LI min P | LI members |
|---|---|---|---|---|---|---|---|
| 0 off | 4910.4 | 12/12/10/11 | 0.9485 | 4592.3 | 11/11/9/11 | **0.5031** | 101 |
| 1 levels | 4919.7 | 12/12/10/11 | 0.9707 | 4629.1 | 11/11/9/11 | 0.9339 | 101 |
| 2 houses | 4909.8 | 12/12/10/11 | 0.9345 | 4591.4 | 11/11/9/**10** | 0.9980 | 101 |
| 3 shrines | 4921.5 | 12/12/10/11 | 0.9771 | 4604.9 | 11/11/9/11 | 0.6484 | 101 |
| 4 tools | 4907.9 | 12/12/10/11 | 0.9338 | 4576.9 | 11/11/9/**10** | 0.9935 | 101 |
| all | 4926.9 | 12/12/10/11 | 0.9870 | 4629.8 | 11/11/9/11 | 0.9157 | 101 |
| **+admission** | **4926.9** | 12/12/10/11 | **0.9870** | **4640.8** | 11/11/9/11 | **0.9333** | **106** |

Step points are **4900 / 4600 in every single run**.

### 2.3 The plan's tier prediction was WRONG, and this is the correction

R5 stated: *"Tiers are now expected to be **gained**, particularly on LI where the
combined slice is +6.00%; any tier that is lost is a surprise."* **No tier was gained,
on either guild, in any run.** A ~6.7% rate improvement is nowhere near a tier
boundary — the boundaries are 400 target units per tier level and the parties were
mid-ramp, not near a crossing. The prediction confused "the rate rises a lot" with
"the tier changes", and the ramp/step structure of partial credit is exactly what
makes those different questions.

**Where the gain actually went is safety, and it is worth more than a tier.** LI's
thinnest trial goes from a coin flip (`P(holds) = 0.5031`, partial fraction 0.0002 —
two ten-thousandths past the boundary) to **0.9333**. SC's goes 0.9485 → 0.9870.
That is the pathology R0 §1 predicted would clear, clearing.

### 2.4 The two tier LOSSES are harness artefacts, not shipped behaviour

Runs 2 and 4 — the two adverse slices — each drop LI's Tailoring trial to tier 10,
costing 100 step points. This is fully explained: that trial banked tier 11 with
0.02% to spare, so *any* downward nudge loses it. Both the joint run and the shipped
run keep tier 11 with a 0.93 hold probability. A slice run **alone** is not a
configuration anyone ships.

### 2.5 Controls

- **SC admission control:** SC run 5 is **byte-identical** to SC run "all" (provenance
  aside). SC admits nobody, so the admission path must not touch it. It does not.
- **Slice 0 golden:** run 0 reproduces R0's every number — tiers, points, credit,
  expected, party sizes — with **zero** pre-existing fields changed. The only
  differences are R4's four additive member keys and the `provenance` block, which
  correctly reads `enabled: false, source: "manual tab", roster_backed: 0`.
- **Suite:** 358 passed with every switch **on**.

### 2.6 Admission, and LI's change of regime

LI: 100 roster-backed, 1 manual-only (`OTZ`, kept), 5 admitted, 7 hiding gear,
captured 2 days old, not stale.

**LI is now seat-constrained for the first time.** 106 members against 4 × 26 = 104
seats; all four parties sit at cap and two members are benched. SC remains
member-constrained (107 in 112). The two guilds are now in different regimes.

**Risk 10 did not fire.** The fear was that LI would bench precisely the admitted
members, whose missing `top`/`bot` understates them by up to 0.2364 efficiency. The
bench is `zzzZap` (an existing member) and `IronPugs` (admitted) — one of each, not
both admitted. And `IronPugs` is the weakest of the five by a wide margin
(C.Smithing 93, Enhancing 93, against LI medians of 109 and 102), so the decision
stands on its own merits rather than on a data gap.

The other four are seated: `yiyya`, `yiyaa` and `U3` in Enhancing, `auuughhh` in
Tailoring. Both halves of the pair §5.6 feared was one renamed person are on the
field, as two people, which is the outcome the characterId argument predicted.

Admission alone is worth **+11.0 expected points** to LI.

## 3. R6 — recalibrating `RISK_SIGMA_SYSTEMATIC`

### 3.0 The prediction, recorded BEFORE the campaign was run

Written 2026-09-01, with `RISK_SIGMA_SYSTEMATIC = 0.0131` still shipped and no
post-merge campaign yet run:

> **Sigma shrinks but does not vanish.** `calibrate.py` prices `augment=±3 per
> slot`, `tool_flip=0.03` and `house`/`house_blank` as uncertainty; all three are
> now *observed* per member for a roster-backed member+skill, so retiring them
> must cut the systematic remainder. It cannot cut it to zero, because the
> unmodelled neck / ring / earring gear (`gear_speed=0.03`,
> `gear_efficiency=0.10`, `gear_gathering=0.05`) is untouched — the roster does
> not carry those slots unless the upstream `stableGear` toggle is switched on
> (plan §11.2) — and that term is **not** the small one.
>
> **A sigma at or near zero would be a bug, not a triumph.** It would mean
> provenance was being respected for uncertainties that remain genuinely
> unknown, and the published `P(holds)` would become over-confident on exactly
> the thin trials the risk bridge exists to flag.

The ablation table in §3.2 is what settles it, and §3.3 records whether the
prediction held.

### 3.1 The prerequisite the plan omitted

`calibrate.main` fetched the manual tab and **never merged the roster**. It raced
rows nobody publishes: stale levels, checkbox tools at an assumed +7, and every
member held at shrine level 1 while the roster reports a mean of 2.99 (SC). Worse,
it made `Sources.respect_provenance` inert *by construction* — there was no
provenance on those rows to respect — so R6 as written would have re-measured the
old uncertainty and reported it as the new one, which is worse than not measuring.

Fixed first: `main` now joins and merges exactly as `build._fetch_guild` does,
gated on the same `config.ROSTER_SOURCE_ENABLED`, and runs `audit_roster_tools` on
the result so the campaign prices what the build prices. Three further gaps in the
same function fell out of doing it:

- **`house_pool` was never passed.** `DEFAULT.house_blank=True` was therefore
  inert from the CLI, and a blank H cell contributed no uncertainty at all. The
  0.0131 being replaced was measured with that gap open.
- **`Sources.label()` filtered `v not in (0, 0.0, 1.0)`**, and `True == 1` in
  Python, so every boolean switch — `house_blank`, `stochastic`,
  `respect_provenance` — was dropped from the label of the very run it governed,
  and `house=1` with them. Every figure transcribed out of this report is
  identified by that string.
- **`ablation()` read `DEFAULT.respect_provenance`** rather than the campaign's
  own. Caught by running the campaign twice and noticing the two tables agreed to
  the last digit on every row: the "before" column was a forgery. It now inherits
  the run's treatment, which is what makes §3.2 a paired table.

The shrine read in `_prepare_perturbed` also moved from `guild_shrine_bonuses()`
to `trials._resolve_shrine(member)`. That was not optional: the harness's golden
identity (`selftest`: with every source off it must BE `simulate_race`) breaks the
moment the merge supplies real per-member levels and the mirror keeps reading the
guild map. It reports `max relative deviation 0.00e+00` on all eight live parties.

### 3.2 The ablation — the full table, both treatments

Live, post-merge, on the **shipped sign-up plan** for each guild (not the
unconstrained optimum: the plan is what actually runs). 20 000 reps, seed
20260901, `--reps 20000` for the headline and `reps/4 = 5000` per ablation row.
"ON" is the shipped campaign (`respect_provenance=True`); "OFF" is
`--ignore-provenance` — *the same post-merge lineup with the observed quantities
priced as unknown anyway*, which is the honest control. Note it is not "revert to
the checkbox": OFF draws ±3 enhancement levels around the member's **observed**
level, not around an assumed +7.

Every figure is `sd(ln tau)` at that trial's marginal tier.

**SC** — parties 28 / 23 / 28 / 28, step total 4900

| source | C.Smithing | Milking | Enhancing | Tailoring | |
|---|---|---|---|---|---|
| level (common drift) | 0.0000 | 0.0000 | 0.0000 | 0.0000 | off by design |
| level (independent) | 0.0000 | 0.0000 | 0.0000 | 0.0000 | off by design |
| house | 0.0020 → **0.0000** | 0.0021 → **0.0000** | 0.0011 → **0.0000** | 0.0018 → **0.0000** | OFF → ON |
| augment | 0.0064 → **0.0022** | 0.0057 → **0.0028** | 0.0023 → **0.0020** | 0.0054 → **0.0024** | OFF → ON |
| tool checkbox | 0.0008 → 0.0008 | 0.0008 → 0.0008 | 0.0002 → 0.0002 | 0.0009 → 0.0009 | unchanged |
| gear: neck speed | 0.0015 | 0.0018 | 0.0022 | 0.0016 | **untouched** |
| gear: neck efficiency | 0.0081 | **0.0103** | **0.0106** | 0.0085 | **untouched** |
| gear: ring/earring | 0.0000 | 0.0055 | 0.0000 | 0.0000 | **untouched** |
| turnout | 0.0000 | 0.0000 | 0.0000 | 0.0000 | off by design |
| model form (target) | 0.0000 | 0.0000 | 0.0000 | 0.0000 | off by design |
| STOCHASTIC (per-action) | 0.0163 | 0.0185 | 0.0118 | 0.0156 | the aleatoric floor |
| **ALL (combined), ON** | 0.0183 | **0.0221** | 0.0160 | 0.0179 | |
| **ALL (combined), OFF** | 0.0192 | **0.0232** | 0.0162 | 0.0187 | |

**LI** — parties 26 / 26 / 26 / 26, step total 4500

| source | C.Smithing | Milking | Enhancing | Tailoring | |
|---|---|---|---|---|---|
| house | 0.0020 → **0.0000** | 0.0021 → **0.0003** | 0.0011 → **0.0000** | 0.0018 → **0.0000** | OFF → ON |
| augment | 0.0064 → **0.0023** | 0.0057 → **0.0028** | 0.0023 → **0.0019** | 0.0054 → **0.0028** | OFF → ON |
| tool checkbox | 0.0008 → 0.0008 | 0.0011 → 0.0011 | 0.0000 → 0.0000 | 0.0011 → 0.0012 | unchanged |
| gear: neck speed | 0.0016 | 0.0016 | 0.0023 | 0.0016 | **untouched** |
| gear: neck efficiency | 0.0087 | **0.0095** | **0.0110** | 0.0084 | **untouched** |
| gear: ring/earring | 0.0000 | 0.0046 | 0.0000 | 0.0000 | **untouched** |
| STOCHASTIC (per-action) | 0.0150 | 0.0168 | 0.0115 | 0.0138 | the aleatoric floor |
| **ALL (combined), ON** | 0.0176 | 0.0205 | 0.0164 | 0.0168 | |
| **ALL (combined), OFF** | 0.0187 | 0.0212 | 0.0165 | 0.0176 | |

**Three readings of this table, in order of how much they matter.**

1. **`house` goes to exactly zero and `augment` falls by two thirds.** Those are
   the two sources the roster turned into observations, and the ablation is where
   you can see it happen. `augment` does not vanish because only the TOOL slot is
   observed: the cape, the family piece and the skilling top/bottom are still
   assumed +7/+3 and still drawn, because no source this repo reads carries them.
   LI Milking's residual `house` 0.0003 is the six manual-only LI members.
2. **`tool checkbox` does not move at all**, and that is not a bug. Once the
   roster names the item, `trials._tool_terms`'s precedence never consults the
   checkbox, so the flip was *already* dead for a roster-backed member in both
   treatments — it only ever moved the gear-hiders, and it still does. Gating it
   under `respect_provenance` states the intent; it does not change a number.
   Pinned by `test_a_named_roster_tool_makes_the_checkbox_flip_inert_either_way`.
3. **The largest surviving systematic row is the unrecorded neck slot**, at
   0.0081–0.0110, and this change does not touch it. That single row is larger than
   everything R6 retired, put together and in quadrature.

### 3.3 The new constant, and whether the prediction held

`systematic = sqrt(sigma_campaign^2 - sigma_aleatoric^2)` at each trial's marginal
tier — the same derivation the config comment records for the 0.0131 it replaces.
`sigma_aleatoric` is `trials.clear_sigma`, i.e. the shipped Wald first-passage
formula, so the remainder is exactly what the constant is defined to be.

| guild | trial | tier | sigma_total | aleatoric | systematic ON | systematic OFF |
|---|---|---|---|---|---|---|
| SC | C.Smithing | 12 | 0.0183 | 0.0162 | 0.0085 | 0.0102 |
| SC | **Milking** | **12** | **0.0221** | **0.0183** | **0.0123** | **0.0141** |
| SC | Enhancing | 10 | 0.0160 | 0.0116 | 0.0109 | 0.0113 |
| SC | Tailoring | 11 | 0.0179 | 0.0154 | 0.0092 | 0.0106 |
| LI | C.Smithing | 11 | 0.0178 | 0.0149 | 0.0098 | 0.0112 |
| LI | Milking | 11 | 0.0203 | 0.0170 | 0.0112 | 0.0127 |
| LI | Enhancing | 9 | 0.0164 | 0.0115 | 0.0117 | 0.0119 |
| LI | Tailoring | 10 | 0.0168 | 0.0140 | 0.0094 | 0.0107 |

**Shipped: `RISK_SIGMA_SYSTEMATIC = 0.0123`**, the bold row — the largest of the
eight, because one constant serves both guilds and the seven others are then
over-covered, which is the direction this constant is documented as erring in. The
maximum lands on the *same row* in both treatments, so the before/after is a
comparison of one row and not of two different ones.

Seed stability, same row, 20 000 reps: **0.0123** (seed 20260901), **0.0120**
(20260801), **0.0121** (777). Spread ±0.0002; the maximum is quoted, not the mean.
A first pass at the plan's default `--reps 4000` put this row at 0.0110 and the
maximum on a different trial — the eight remainders were then separated by less
than their own error bars, because `d(systematic)/d(sigma_total)` is
`sigma_total/systematic ≈ 1.8`, so the remainder amplifies the campaign's noise.
**4000 reps is not enough to rank these eight rows; 20 000 is.** That is a
correction to the plan's stated default, not a shortcut taken against it.

**THE PREDICTION HELD.** Sigma shrank — 0.0131 → 0.0123 against the shipped
constant, and 0.0141 → 0.0123 against the control, which is the recalibration
proper — and it did not come close to vanishing. §3.2's third reading is why: the
unrecorded neck slot survives in full at 0.0081–0.0110 and is not the small term.

### 3.4 R6.4 — the compounding trap, checked

R5 made the parties faster and R6 makes the risk discount smaller, so both push
`expected_points` the **same** way. A bug in either would look confirmatory.

**The plan's stated invariant is too strong, and this is the correction.** Plan
§7 R6.4 asks that `credit_points` "must not move at all between the R5 and R6
manifests". It can, legitimately: `config.OPT_OBJECTIVE = "expected"` means the
**optimizer** maximises `expected_credit_points`, which reads
`RISK_SIGMA_SYSTEMATIC` — so a new sigma can re-seat the parties and carry
`credit_points` with them. (`expected_credit_points`'s own docstring still claims
it "never enters `src.optimizer.AssignmentScorer`"; `optimizer._objective_value`
calls it. The docstring is stale.) The invariant that actually detects a leak is
the one about a **fixed** lineup:

> Score a FIXED assignment at two sigmas. `tier_reached`, `partial_fraction`,
> `credit_points`, `points` and both totals must be **identical** — they are
> `+ - * / floor` over rates the risk model does not enter. If they move, the
> recalibration has leaked into the rate model.

Checked two ways. Offline and permanently, by
`tests/test_calibrate.py::test_the_deterministic_score_does_not_depend_on_risk_sigma_systematic`.
And live, on **frozen inputs** — one fetch, one merge, both sigmas scored off the
same member list — because a live rebuild against §2.2's manifest could not have
made the claim: the LI manual tab has gained five rows since R5 shipped (106
manual + 5 admitted = 111 merged, against R5's 101 + 5 = 106), so a same-day
comparison of two builds would be measuring an officer's edits as well as sigma.

**The live check, on frozen inputs.** Both guilds' **shipped sign-up plans** (the
parties that actually run, read out of `_site/signup.json` as
`calibrate.load_seats` reads them — no optimiser search, so no search noise),
scored at 0.0131 and at 0.0123 off one fetch:

| | SC | LI |
|---|---|---|
| members merged | 107 | 111 |
| seats | 28+23+28+28 = 107 | 26+26+26+26 = 104 |
| step points | 4900 → **4900** | 4500 → **4500** |
| credit points | 4924.496681581572 → **4924.496681581572** | 4585.709227696125 → **4585.709227696125** |
| tiers | 12/12/10/11, unchanged | 11/11/9/10, unchanged |
| partial fractions | unchanged, to the last digit | unchanged, to the last digit |
| E[points] | 4923.0269 → 4923.2341 (**+0.2072**) | 4585.7921 → 4585.7875 (**−0.0046**) |
| P(holds) moved | 2 of 4 | 0 of 4 |

**`credit_points` is identical to the last digit on both guilds. No leak.**

Two features of that table are worth reading rather than skimming:

- **SC's E rises and LI's falls**, by very different amounts, and both are
  correct. Where `E < credit` — SC's C.Smithing at P = 0.982 and Tailoring at
  0.987 — the expectation is being docked for risk, so cutting sigma returns some
  of it. Where `E > credit` — every LI trial, all four saturated at P = 1.0000 —
  the expectation is *above* the deterministic score because the upside (running
  further into the next tier than the point estimate) outweighs a downside that no
  longer exists, and a narrower shock distribution takes some of that upside away.
  A recalibration that moved every trial the same way would be the suspicious
  result, not this one.
- **Two of SC's four P(holds) do not move at all, and none of LI's do**, because
  they are already exactly 1.0. LI's whole plan has left the region where sigma
  can reach it — which is R5's safety gain, showing up in R6's arithmetic.

The R5→R6 manifest comparison the plan also asks for is **not** available as a
same-day pair of live builds, and this is the reason: the LI manual tab gained
five rows between R5 shipping and R6 running (101+5 = 106 merged then, 106+5 = 111
now), so the difference between two builds would carry an officer's edits as well
as the constant. The frozen-input pair above is the stronger claim, not a weaker
substitute for it — it varies one thing where a rebuild would have varied two.

**And the optimiser DOES re-seat**, which settles the last piece. Four full
searches on the same frozen inputs, unconstrained optimum, seed 42:

| | step | credit | E[points] | search re-seated |
|---|---|---|---|---|
| SC @ 0.0131 | 4900 | 4928.0720 | 4926.9959 | — |
| SC @ 0.0123 | **4900** | **4927.8284** (−0.244) | 4927.0258 (+0.030) | **yes**, 4 members |
| LI @ 0.0131 | 4600 | 4652.7648 | 4650.9739 | — |
| LI @ 0.0123 | **4600** | **4653.7680** (+1.003) | 4651.4217 (+0.448) | **yes**, 6 members |

`credit_points` moves, **in opposite directions on the two guilds**, and the step
points do not move at all. SC's search gives up 0.244 deterministic credit points to
buy 0.030 expected ones; LI's happens to gain on both. That is precisely what
maximising `E` means under a new sigma, and it is the direct refutation of the
plan's "must not move at all": a new risk constant is a new objective, so a
different assignment is a **consequence**, not a leak. What must not move — and does
not — is the score of a lineup somebody else chose.

The re-seats are small and local, four members on SC and six on LI, all of them
swaps between trials rather than changes to who is seated at all:

```
SC  C.Smithing −IronMessiah −Living2Die  +IronAegis +Mike111
    Milking    −Mike111                  +IronGoatMilkBEST +IronMessiah
    Enhancing  −IronGoatMilkBEST         +Atka
    Tailoring  −Atka −IronAegis          +Living2Die
```

**One incidental finding, and it is not small.** Those four searches took over an
hour. `build.py`'s timing table records ~85 s per guild for `run_week`, but that
table was measured on 2026-08-14 and `OPT_OBJECTIVE = "expected"` landed after it —
and the expected objective calls `clear_sigma` and `_cumulative_tier_times` inside
*every* objective evaluation, of which the search makes ~87 000. **The build is
therefore far slower than its own documented figures**, and nobody had noticed
because the only thing that ever runs a full search is CI, where it is measured in
nothing but a green tick. `README.md`'s "Where the run time goes" and `build.py`'s
table both need re-measuring; that is out of this change's scope and is recorded
here so it is not lost.

### 3.5 One thing R6 broke, which was worth breaking

`tests/test_roster.py::test_roster_disabled_reproduces_the_golden_week` failed on
the new constant, on `Milking.clear_probability`. It was right to fail and the test
was wrong: **that golden pins the RATE MODEL, and two of the fields it compares are
built from the RISK constant** (`clear_probability` and `expected_points`). Nothing
had made the distinction because `RISK_SIGMA_SYSTEMATIC` had never moved before, so
a test whose subject is *which parties the search chose and what they scored* was
quietly also pinning a number measured by `src/calibrate.py`.

Fixed by pinning the constant inside the test, by name, at the value the golden was
generated under — not by regenerating the golden and not by loosening a tolerance.
The constant's own movement is checked where it belongs, in
`tests/test_calibrate.py`.

## 4. R7 — the shrine caps and the two probes, measured

### 4.1 The caps, and why they are a FLOOR rather than a measurement

Observed per-member maxima on the roster tabs, 2026-09-01 (SC 107 rows, LI 105):

| shrine | SC cap | SC mean | SC distribution | LI cap | LI mean | LI distribution |
|---|---|---|---|---|---|---|
| force | **4** | 2.99 | 0:5, 1:13, 2:13, 3:23, 4:53 | **3** | 2.30 | 0:10, 1:5, 2:34, 3:56 |
| tempo | **4** | 3.13 | 0:7, 1:6, 2:12, 3:23, 4:59 | **3** | 2.31 | 0:10, 1:7, 2:28, 3:60 |
| spirit | **2** | 1.04 | 0:44, 1:15, 2:48 | **1** | 0.81 | 0:20, 1:85 |
| scholar | **2** | 1.36 | 0:28, 1:12, 2:67 | **1** | 0.76 | 0:25, 1:80 |
| rarity | **0** | 0.00 | 0:107 | **0** | 0.00 | 0:105 |

A member cannot buy past the cap, so the maximum is a **floor** on it, not a
measurement of it. Where nobody has bought anything the floor is 0 and the true cap
is unknown — which is the rarity row on both guilds, and the probes say so by
pricing the first level rather than by claiming the shrine is maxed.

**The old single map was stale as a cap, not merely coarse.** `GUILD_SHRINE_LEVELS`
carries force 1 / tempo 1 from a `guild_updated` capture of 2026-07-22. Members are
observed at force 4 on SC and cannot exceed the cap, so SC's shrine level has risen
to at least 4 since that capture. The caps above are the only current evidence this
repo holds, and the spread in the distributions is by itself proof that the level is
not a guild-wide grant: one grant cannot produce five different values.

### 4.2 The plan met the real code badly here, and the split is three-way

Plan §7 R7.1 says to "split `config.GUILD_SHRINE_LEVELS` per guild and re-point its
meaning at the guild's cap". Done that way it would have been **wrong twice**:

- `GUILD_SHRINE_LEVELS` still feeds the **rate model**, in two places the plan does
  not mention — `ROSTER_USE_SHRINES = False` (the whole shrine rollback, which
  restores `simulate_race`'s once-per-race hoist bit-for-bit) and the per-shrine
  fallback for a member whose roster column is blank. Re-pointing it at the cap
  would have moved both, and would have broken
  `test_roster_disabled_reproduces_the_golden_week` — the rollback proof.
- Reading a **blank** column as "at the cap" is optimistic about precisely the case
  we cannot see. The conservative reading is the modelled level, which is also the
  one that keeps the rollback exact.

So there are now two maps with two jobs, and the config comment's main work is
stopping anyone conflating them: `GUILD_SHRINE_LEVELS` is the modelled guild-wide
**fallback** (unchanged, force 1 / tempo 1), and `GUILD_SHRINE_CAPS` is the
per-guild **cap**, which feeds the two probes and nothing in the rate model.

### 4.3 The two probes, live, on the published parties

Both probes hold the parties fixed, exactly as `probe_building_upgrade` does.
`points_gained_immediate` is `0.0` on all ten rows, **by construction** —
`tests/test_trials.py::test_probe_shrine_upgrade_immediate_gain_is_zero` asserts it
across four different mixes of member levels, including the mix where every member
sits at the cap, which is the only one where a cap raise reaches anybody.

**SC** — 107 seated of 107 merged (parties 28/24/28/27)

| shrine | cap | mean held | below cap | levels unbought | **free gain/wk** | at cap | day-1 | full-adoption gain | gp | weeks to repay |
|---|---|---|---|---|---|---|---|---|---|---|
| force | 4 | 2.99 | **54 of 107** | 108 | **+1.658** | 53 | 0.0 | +0.501 | 3300 | 6590 |
| tempo | 4 | 3.13 | 48 of 107 | 93 | +0.754 | 59 | 0.0 | +0.547 | 3300 | 6028 |
| rarity | 0 | 0.00 | 0 of 107 | 0 | loot only | 107 | 0.0 | 0.0 | 1000 | — |
| spirit | 2 | 1.04 | 59 of 107 | 103 | loot only | 48 | 0.0 | 0.0 | 1800 | — |
| scholar | 2 | 1.36 | 40 of 107 | 68 | XP only | 67 | 0.0 | 0.0 | 1800 | — |

**LI** — 104 seated of 111 merged (parties 26/26/26/26, all four at cap)

| shrine | cap | mean held | below cap | levels unbought | **free gain/wk** | at cap | day-1 | full-adoption gain | gp | weeks to repay |
|---|---|---|---|---|---|---|---|---|---|---|
| force | 3 | 2.31 | **48 of 104** | 72 | **+0.861** | 56 | 0.0 | +1.078 | 2450 | 2272 |
| tempo | 3 | 2.34 | 44 of 104 | 69 | +0.648 | 60 | 0.0 | +0.611 | 2450 | 4013 |
| rarity | 0 | 0.00 | 0 of 104 | 0 | loot only | 104 | 0.0 | 0.0 | 1000 | — |
| spirit | 1 | 0.82 | 19 of 104 | 19 | loot only | 85 | 0.0 | 0.0 | 1350 | — |
| scholar | 1 | 0.77 | 24 of 104 | 24 | XP only | 80 | 0.0 | 0.0 | 1350 | — |

**Against the expected counts.** SC force **54 of 107 — exact**. LI force reads
**48 of 104**, against the expected 49 of 105: the probe's denominator is SEATS, and
LI now seats 104 of its 111 members, so one of the 49 below-cap members is benched.
On the whole-roster denominator the probe's own inputs reproduce **49 of 105
(mean 2.30) exactly**. The two numbers answer two different questions and both are
printed; the page quotes the seated one, because a benched member's shrine purchase
does not move this week's rate.

### 4.4 One claim in §5.5 does not survive its own measurement

Plan §5.5 calls the adoption probe "the more actionable of the two by a wide
margin". Actionable, yes. **Bigger, not always:** on SC's force the free headroom is
worth +1.658 against a cap raise's +0.501, but on **LI it is +0.861 against
+1.078** — the cap raise wins on size there.

It still loses, and for a better reason than size: the raise costs 2450 guild points
and takes ~2270 weeks to repay them, while closing the headroom costs **nothing** and
pays this week. So the page's ordering is justified on **price and immediacy**, not
on magnitude, and the copy says exactly that. Pinned in both directions by
`test_adoption_beats_the_cap_raise_on_a_party_below_the_cap`, which also asserts the
reverse case, so the page copy cannot drift back into the stronger claim.

### 4.5 What R7 does not touch

No rate, no tier, no point. Verified: both probes' `credit_points_now` is `==` the
live week's own `sum(simulate_race(...).credit_points)` on both guilds
(4927.78262769608 SC, 4644.2161825465855 LI), so the probes are reading the same week
the page publishes rather than a private re-derivation. And the golden week is
reproduced with the probe changes reconciled key by key, including the load-bearing
equality that the re-specified full-adoption gain equals the old `points_gained`
**exactly** — computed a different way (per-member replacement rows rather than a
temporary rebinding of `config.GUILD_SHRINE_LEVELS`), which is what proves the new
arithmetic re-associated nothing.

## 5. Closing — what this change actually did, in one place

| | before (R0) | after (R8) |
|---|---|---|
| per-member source | one hand-maintained tab | scripted harvest, manual tab per field, constants last |
| SC step points | 4900 | **4900** |
| LI step points | 4600 | **4600** |
| SC E[points] | 4910.4 | **4926.9** |
| LI E[points] | 4592.3 | **4640.8** |
| SC thinnest `P(holds)` | 0.9485 | **0.9870** |
| LI thinnest `P(holds)` | **0.5031** | **0.9333** |
| LI members | 101 | **106** at the flip, 111 today |
| shrine levels in the model | 1, for everybody | each member's own purchase (means 2.99 / 2.30) |
| `RISK_SIGMA_SYSTEMATIC` | 0.0131 | **0.0123** |
| unbought shrine headroom | invisible | **54 of 107 (SC), 49 of 105 (LI)**, and priced |

**No tier was gained.** That is the headline correction to the plan and it is worth
repeating, because "the rate rose 6.7%" and "the tier changed" are different
questions and the plan conflated them. Tier boundaries are 400 target units apart
and both guilds' parties were mid-ramp.

**What the change actually bought is that the numbers are now true.** LI's Tailoring
trial was banking tier 11 with two ten-thousandths of a percent to spare and the page
said `P(holds) = 0.5031` — an honest report of a lineup chosen against dishonest
inputs. The same trial now holds the same tier at 0.9333. A reader glancing at the
page sees almost nothing different; what changed is that it is no longer a coin flip
dressed as a plan.

**And one thing shipped stale for a cycle, which is recorded rather than tidied
away.** The flip (R5) went out against a `RISK_SIGMA_SYSTEMATIC` that still priced
three now-observed facts as unknowns. Conservative, not wrong — the published figures
were pessimistic rather than falsely reassuring — but stale, and knowingly so, for
one deploy. R6 closed it.

### Three follow-ups this change uncovered and did not do

1. **`build.py`'s timing table and `README.md`'s "Where the run time goes" are badly
   stale** (§3.4). They predate `OPT_OBJECTIVE = "expected"`, which calls
   `clear_sigma` and `_cumulative_tier_times` inside all ~87 000 of the search's
   objective evaluations. Both places are flagged; re-measuring is open, and a
   memoisation pass on `_cumulative_tier_times` may well be the actual fix.
2. **The unrecorded neck / ring / earring slots are now the largest term in the risk
   budget** — 0.0081–0.0110 against a ~0.012 systematic total, larger on their own
   than everything R6 retired. The upstream `stableGear` block (plan §11.2) is the
   fix and is the highest-value remaining work in this area.
3. **`GUILD_SHRINE_CAPS` is a floor, not a measurement** (§4.1). Where nobody has
   bought a level the floor is 0 and the true cap is unknown — rarity, both guilds.
   One `guild_updated` capture would settle it.
