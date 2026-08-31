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
heard of them. `ROSTER_ADMITS_NEW_MEMBERS = False` (plan §5.6) keeps them dropped
for now; the plan's own justification (the `yiyaa`/`yiyya` pair) is sound, but
this raises the question's priority: the roster can now *tell* us they are real.
