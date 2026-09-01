# Handover — roster-as-primary-source: CLOSED 2026-09-01

R0–R8 are complete. Nothing is outstanding in this change. What follows is the
short version plus the follow-ups it uncovered; the measurements live in
`research/roster-as-primary-source.md`, the reasoning in
`.claude/plans/roster-as-primary-source-implementation-plan.md`, and the
reader-facing account in `README.md` § "Where member data comes from".

## What shipped

The scripted roster tab is the primary per-member source: real levels, real house
rooms, per-member purchased shrine levels, real tool tier and augment level, with
the manual tab as a per-field fallback and the old constants as last resort. Five
previously-dropped LI members are seated. `RISK_SIGMA_SYSTEMATIC` is recalibrated
to 0.0123. The shrine probes have been re-specified around the corrected mechanic
(the guild's level is a **cap**), and a new `probe_shrine_adoption` leads the page.

Step points did not move on either guild — 4900 / 4600, before and after. The gain
is in *safety*: LI's thinnest trial went from a coin flip (`P(holds) = 0.5031`) to
0.9333, SC's from 0.9485 to 0.9870.

## THE OPEN PROBLEM — RESOLVED

The CI-only failure of `test_roster_disabled_reproduces_the_golden_week` was **one
ULP in `clear_probability`**, from a libm difference between glibc on Linux
x86-64 and macOS ARM64. Reproduced in a bookworm container, fixed in `526594b` on
`main`: the golden's comparison is split by what is actually portable — pure
`+ - * / floor` stays on `==`, the two fields built from `math.erf` / `log` / `exp`
move to `rel=1e-12`. The full account is in that commit's message and in the test's
own comment, which is where it belongs.

Two of the four disproven hypotheses recorded in the previous version of this note
were, in hindsight, circling the answer: hypothesis 1 perturbed `_normal_cdf` by one
ULP in *one* place and found nothing move, which was read as exonerating libm when it
only showed that the *search* is not ULP-fragile here. The reserve candidate
"platform libm" was the right one.

**Consequence worth keeping:** the search's ULP-exactness is still pinned by `==`.
Only two reported probabilities are not. Do not loosen anything else without
measuring first.

## Follow-ups this change uncovered and did not do

- **`build.py`'s timing table and `README.md` § "Where the run time goes" are
  stale, badly.** They predate `OPT_OBJECTIVE = "expected"`, which calls
  `clear_sigma` and `_cumulative_tier_times` inside every one of the search's
  ~87 000 objective evaluations. Four full searches locally took over an hour
  against the ~4m50s the table predicts. Flagged in both places; needs
  re-measuring, and may well warrant a memoisation pass on `_cumulative_tier_times`.
- **`expected_credit_points`' docstring is stale.** It says the function "never
  enters `src.optimizer.AssignmentScorer`"; `optimizer._objective_value` calls it.
  Harmless as code, actively misleading as documentation — it is what made the
  plan's R6.4 invariant too strong.
- **The unrecorded neck / ring / earring slots are now the largest term in the
  risk budget**, at 0.0081–0.0110 against a ~0.012 systematic total, and larger on
  their own than everything R6 retired. The upstream `stableGear` block (plan
  §11.2) is the fix and is the highest-value remaining work in the whole area.
- **`config.TOOL_ENHANCE_WHEN_UNKNOWN = 0` is still never exercised on live data**
  (zero named-tool-with-blank-enhancement observations on either guild), so it
  remains untested against reality rather than merely provisional.
- **`GUILD_SHRINE_CAPS` is a floor, not a measurement.** Where nobody has bought a
  level the floor is 0 and the true cap is unknown — rarity on both guilds. A
  `guild_updated` capture would settle it.
