# SURVEY CORPS — Guild Skill Register

Static site that mirrors a public Google Sheet skill register for the
Milky Way Idle guild **SURVEY CORPS**, and publishes it to GitHub Pages.

The pipeline is one-directional and credential-free:

```
public Google Sheet  ──(anonymous CSV export)──▶  Python  ──▶  _site/  ──▶  GitHub Pages
```

No Google Sheets writes, no API keys, no service accounts. It only reads the
sheet's published CSV export (`?format=csv`), which works because the sheet is
shared as "anyone with the link".

## What it does

1. **Fetch** the sheet as CSV (`src/reader.py`).
2. **Parse** it into typed `MemberRow` / `SkillEntry` dataclasses, validating the
   header against sentinel columns so a sheet restructure fails loudly.
3. **Process** rows into a summary (`src/processor.py`) — *this is the seam for
   future custom logic*; today it computes member count and per-skill averages.
4. **Build** `_site/index.html` (self-contained, inline CSS) and
   `_site/data.json` (`src/build.py`).

## Run locally

This project uses [uv](https://docs.astral.sh/uv/) (matching CI):

```bash
uv run python -m pytest tests/ -v          # offline unit tests
uv run --extra dev python -m src.optimize_bakeoff   # optimizer bake-off (needs scipy extra)
uv run --no-dev python -m src.build        # live fetch -> writes _site/
open _site/index.html
```

`--no-dev` keeps the optional `[dev]` extras (`scipy`/`numpy`/`pytest`) off the
build path — the shipped optimizer is pure-Python. Plain `pip install -e ".[dev]"`
still works if you prefer a classic venv.

## Guild Trials optimizer (Phase 2)

`src/trials.py` models each weekly skilling trial as a cumulative tier race and
scores it in guild points; `src/optimizer.py` assigns members across the week's
**4 trials to maximise total points**. The objective is non-linear and
non-separable — points are a step function of the tier reached, and the 1%
per-member headcount penalty means a weak member can *lower* a party's tier, so
party size is itself a decision. Every strategy is therefore judged against the
real `simulate_race` oracle (memoised in `AssignmentScorer`).

The shipped default is the ensemble strategy `"best"`
(`config.TRIAL_OPTIMIZER_STRATEGY`): it runs several strong pipelines — including
a **beam-search-seeded genetic algorithm** — and returns the single best result.
`src/optimize_bakeoff.py` is the harness that compared the field (see the
`# BAKE-OFF RESULTS` block in `config.py`). To restore the Phase-1 random split,
set `TRIAL_OPTIMIZER_STRATEGY = "random"` (a one-line rollback).

## Sign-up optimiser (real sign-ups)

`src/signup.py` reads the sheet's **SC Trial Signup** tab — the guild's *actual*
weekly volunteers — and builds `_site/signup.html` + `signup.json`:

1. **Sign-ups are enforced.** Every member who ticked a trial is locked into it
   (shown green) and is never moved or benched.
2. **Open seats are recommended fills.** Remaining seats (to the per-party cap)
   are offered only to members who signed up for *nothing* (shown blue), and only
   where they do not lower a party's tier — the same no-regret rule as
   `optimizer._fill_bench`.
3. **Swaps to reach optimal.** The page lists the minimal set of
   *strictly-improving* moves from the enforced plan toward the unconstrained
   full-roster optimum, each annotated with the guild points it gains. The
   optimum reuses the exact assignment `trials.html` already computes (no second
   optimizer run — the two pages never disagree on the ceiling).

The SC Trial Signup tab is `col 0 = User`, then one TRUE/FALSE column per skill in
`config.SKILLS` order (col 9, "Bell Farming", is the Alchemy trial). Only this
week's drawn skills carry ticks; parsing is positional and guarded by the "User"
sentinel (gviz silently serves a different tab on a bad name).

## Deploy (GitHub Actions)

`.github/workflows/deploy.yml` builds and deploys on a **daily** schedule and on
manual dispatch, using `uv` (via `astral-sh/setup-uv`, cached) and the
artifact-based Pages flow (`actions/upload-pages-artifact` + `actions/deploy-pages`).
The schedule is daily rather than hourly because the Phase 2 optimizer takes a
couple of minutes per run; hourly would burn ~2000+ Actions minutes/month.

### One-time manual step

After pushing to GitHub, enable Pages:

> **Settings → Pages → Build and deployment → Source: GitHub Actions**

Then trigger the workflow once from the **Actions** tab (or wait for the daily
schedule). Subsequent runs update the site automatically.

## Configuration

All layout assumptions live in `src/config.py` (spreadsheet ID, CSV URL, ordered
skill list, column offsets, and header sentinels). If the sheet layout changes,
`src/build.py` exits non-zero with a `SheetStructureError` describing the
mismatch — update `config.py` to match the new layout.

The member-table structure guard validates two header rows: the real header
(Member / Main Classes / Flex) and the skill-**group** row, whose block-start
cells must spell each `config.SKILLS` name (this pins the block start and the
5-column stride). The 2026-07-19 sheet reformat removed the per-block
`H / Tool / Top / Bot` sub-label cells from the header, so those are no longer
used as sentinels; the data columns behind them are unchanged.
