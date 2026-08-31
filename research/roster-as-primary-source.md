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
