# Handover — roster-as-primary-source, paused 2026-08-31

## Where things stand

**Shipped and pushed to `main` (`8998e36`), R0–R5 complete.** The roster is the
primary per-member source: real levels, real house rooms, per-member purchased
shrine levels, real tool tier and augment level, with the manual tab as a
per-field fallback and the old constants as last resort. Five previously-dropped
LI members are admitted. 358 tests passing locally.

**`main` is RED in CI and nothing is deployed.** The deploy gate held — the live
site still serves the 2026-08-31 06:46 scheduled build. Nothing broken reached
readers.

**Local branch `roster-recalibrate`** is `main` + one WIP commit (`b9caea4`),
which is *incomplete and unverified*. Amend or reset it when R6 resumes.

## THE OPEN PROBLEM — one test, green locally, red in CI

`tests/test_roster.py::test_roster_disabled_reproduces_the_golden_week`
(`1 failed, 357 passed` in run `33401288541`).

It compares a whole `run_week` result against `tests/golden/week_pre_roster.json`
with `==`. Inputs are fully deterministic: synthetic 30-member fixture, seeded
RNG (`tests/golden_fixture.py`), no clock, no network, no sheet.

### Hypotheses tested and DISPROVEN — do not re-tread these

1. **libm / ULP sensitivity of the objective.** `OPT_OBJECTIVE = "expected"` calls
   `math.erf/exp/log/sqrt`, and `_prepare_member`'s docstring records a live
   one-ULP reshuffle. But perturbing `trials._normal_cdf` by exactly one ULP
   (`math.nextafter`) changed **nothing** — same parties, same tiers, same total.
2. **Python version.** Golden matches on **both** 3.13.7 and 3.14.6, identically.
3. **String hash randomisation.** Identical output SHA across
   `PYTHONHASHSEED = 0, 1, 7, 12345, 99999`.
4. **The dev extras.** CI runs `uv run --extra dev`, local runs used `--no-dev`;
   scipy/numpy are installed in CI. The test **passes locally under
   `--extra dev`** too.

### The next diagnostic step

Stop guessing and get CI's actual `got`. Cheapest reliable route: make the test
dump `got` to a file on failure and upload it as a workflow artifact (or add a
temporary step printing a compact digest), then read it against
`tests/golden/week_pre_roster.json`. One CI round trip settles it.

Untested candidates worth holding in reserve, in order of plausibility:

- **Platform libm** (Linux x86-64 glibc vs macOS ARM64), which hypothesis 1 only
  partially probes — it perturbed one function in one place by one ULP, while a
  real platform difference would move several functions at once and possibly by
  more.
- **Cross-test state leakage** with a CI-specific ordering: the test monkeypatches
  only `ROSTER_SOURCE_ENABLED`; another test leaving `ROSTER_USE_*`,
  `GUILD_SHRINE_LEVELS` or `COMMUNITY_BUFF_LEVEL` mutated would change the golden
  week. Local full-suite runs passed, so this needs an ordering difference to
  explain it.

### The judgement call, when the cause is known

The test's *intent* is right — R2/R3 must not perturb the rate model while the
switch is off — but pinning a **ULP-sensitive search's output** with `==` may
simply not be a portable property. If so, the fix is to pin what is genuinely
invariant: `simulate_race` on a **fixed** party (pure `+ - × ÷` and
`math.floor`, portable) exactly, and leave the search's chosen assignment out of
the golden. That preserves the property under test and drops the part that cannot
hold across machines.

**Do not simply loosen it to `approx` or skip it in CI** without knowing the
cause. The whole verification discipline of this change rests on not adjusting a
measurement to make it agree.

### Note on the overnight cron

`deploy.yml` runs daily at 01:00 UTC and will fail the same way, sending another
email. Harmless — the gate blocks publishing — but expect it.

## Remaining work

- **R6 — recalibrate `RISK_SIGMA_SYSTEMATIC`.** Currently 0.0131 and *knowingly
  stale*: it prices augment level, tool tier and blank house cells as unknowns
  when all three are now observed. Conservative rather than wrong, so the live
  figures are pessimistic, not falsely reassuring. **The plan omits a
  prerequisite**: `calibrate.main` (`src/calibrate.py:1081`) fetches the manual
  tab and never merges the roster, so `Sources.respect_provenance` would have no
  provenance to consult and the phase would be inert. That is what `b9caea4`
  began. Prediction to record before the run: sigma **shrinks but does not
  vanish**, because the neck/ring/earring terms are untouched.
- **R7 — shrine probes and the cap.** Split `GUILD_SHRINE_LEVELS` per guild and
  re-point it at the guild's *cap* (measured: SC force 4 / tempo 4 / spirit 2 /
  scholar 2 / rarity 0; LI 3 / 3 / 1 / 1 / 0). `probe_shrine_upgrade` gains
  `points_gained_immediate == 0.0` **by construction** (a test, not an
  observation). Add `probe_shrine_adoption` — SC 54 of 107 and LI 49 of 105 sit
  *below* their cap and can raise their own rate at zero guild spend, which is
  the most actionable finding in the whole change.
- **R8 — README and research note**, including the two corrections R5 produced:
  no tier was gained (the plan predicted otherwise; the gain went into safety),
  and sigma was knowingly stale at deploy time.

## Two things worth remembering about the result

- **LI's coin flip is gone**: thinnest trial `P(holds)` 0.5031 → 0.9333. SC's
  0.9485 → 0.9870. That is the operational win, not the +48.5 expected points.
- **LI is now seat-constrained for the first time**: 106 members against 4 × 26 =
  104 seats, all four parties at cap. SC remains member-constrained (107 in 112).
  The two guilds are in different regimes, which makes the old "is
  `TRIAL_PARTY_CAPS` real?" question live for exactly one of them.
