# Handover — per-item gear from `gearSeen`: CLOSED 2026-09-02

G0–G9 are complete and the switch is ON. Nothing is outstanding in this change.
The measurements live in `research/per-item-gear.md`, the reasoning in
`.claude/plans/per-item-gear-implementation-plan.md`, the raw campaign output in
`research/gear-sigma-campaign-2026-09-02.txt` and `research/gear-reconciliation-2026-09-02.txt`,
and the reader-facing account in `README.md` § "Where member data comes from".

## What shipped

Equipment is read **per item** from the `gearSeen` union: a 39-item catalogue,
transcribed from the game's own data and pinned by a test that regenerates it.
Five constants that asserted the same equipment of every member are gone from the
live path — the cape, the family piece, both garments and the flat gathering
doubling — and the **neck slot is modelled for the first time**, having previously
been carried in `RISK_SIGMA_SYSTEMATIC` as its largest single row.
`RISK_SIGMA_SYSTEMATIC` is recalibrated 0.0123 → 0.0098.

**Step points did not move**: 4900 and 4600, before and after, on both guilds.
Credit points rose 4,932.9 → 4,947.1 (SC) and 4,661.2 → 4,673.5 (LI); the thinnest
trial went from P = 0.9908 to 1.0000 on SC before the search spent any of it back.
The real gain is that **53% of SC's slot resolutions and 51% of LI's are now
measured rather than assumed.**

## The one judgement call, and how to settle it

`GEAR_IMPUTE_FAMILY_PIECE = True` keeps the universal grant of Collector's Boots,
Red Culinary Hat, Eye Watch and Enchanted Gloves, correcting only the enhancement
level. **The measurement disagrees with the decision** and the disagreement is
recorded rather than settled (`research/per-item-gear.md` §3.1): the four pieces
are held all-or-nothing — 48% of visible members show none, 37% show all four —
and the rotation defence fails, because 82 members wear a skilling *necklace*,
proving the capture caught them in skilling kit, while showing not one of the four.

The operator's judgement is that the union has not converged. **Re-run
`research/scratch/gear_survey.py` §4 in a few weeks.** If the "0 of four" column
has not shrunk, the bimodality is real ownership and the switch should move. The
slice is worth only −0.50 (SC) / −1.72 (LI) credit, so being wrong costs little
either way.

## THE LESSON THIS CHANGE ACTUALLY TAUGHT

**Four defects were found, and three of them were in code that only runs when
something is switched off.** A disabled slice dropped its slot instead of
restoring its constant; the accessory rollback lost `GEAR_DOUBLE_CHANCE`; and the
G6 harness disabled the parse at the wrong moment and so measured a guild wearing
nothing, reporting a plausible −5 where the truth was +11. Every test written
before then exercised the switches ON.

A switch documented as "restores X" is a **claim**, and an untested claim about a
rollback is worse than no switch, because it will be reached for in a hurry by
someone already having a bad day.
`test_every_slice_switched_off_reproduces_the_pre_gear_constants` now asserts the
whole assembly across all ten skills and all three channels to 1e-12. Write that
test first next time.

A fourth, smaller lesson: `--ignore-provenance` initially could not move the one
quantity this change observed — `augment` leapt 0.0018 → 0.0075 while every neck
row stayed identical to four decimals. **A control that cannot move its subject
will agree with any result you put beside it.** Check that a control moves the
thing under test before quoting it.

## Follow-ups this change uncovered and did not do

- **Nothing on any page reports per-member gear.** Both gear fields are held out
  of `data.json` (`reader._NEVER_SERIALISED`) because they would add 116 KB to a
  256 KB payload and nothing reads them. A per-member gear badge is the natural
  next step, and deleting one line there is the whole of its data plumbing.
- **`skillingEfficiency` on enhancing is an unverified generic.** The catalogue
  says "applies to all skilling actions" and enhancing is one, but no capture
  confirms it. It affects the 117 members wearing a Philosopher's Necklace and is
  isolable to one row of `gear.STAT_CHANNELS`. A capture of an enhancing trial's
  `efficiency` field would settle it.
- **`gatheringQuantity`'s channel remains open**, as it was before this change.
  `GEAR_GATHERING_IN_RATE = False` now isolates it, which the flat constant could
  not do. It is worth 0.0037–0.0040 of σ on the gathering trial.
- **`signup.plan` and the buff ladder were not re-instrumented.** The build's
  503.6s minus SC's ~440s search leaves ~60s for them and all rendering; that is
  an inference, not a measurement. See README § "Where the run time goes".
- **`GUILD_SHRINE_CAPS` is still a floor, not a measurement** — inherited from the
  roster handover, untouched here. A `guild_updated` capture would settle it.
- **The additive member+item imputation was offered and declined.** Measured, 34%
  of the variance in enhancement level is explained by *who* the member is and 31%
  by *which item*, so the shipped per-item mean discards about a third of the
  available signal (`research/per-item-gear.md` §5). A candidate for a later pass,
  not a defect in this one.
