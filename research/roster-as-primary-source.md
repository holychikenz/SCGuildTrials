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
