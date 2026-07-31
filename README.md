# Guild Skill Register (Survey Corps + Lactose lntolerance)

Static site that mirrors a public Google Sheet skill register for the
Milky Way Idle sub-guilds **Survey Corps** and **Lactose lntolerance**, and
publishes it to GitHub Pages. The build runs the whole pipeline once per guild:
Survey Corps at the site root (`_site/`) and Lactose lntolerance under
`_site/li/` — the two guilds share one spreadsheet (and one weekly trial draw)
but have their own member and sign-up tabs. See `GUILD_SITES` in `src/build.py`.

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
   `_site/data.json` (`src/build.py`) — once per guild (Survey Corps at the
   root, other guilds under their own sub-directory, e.g. `_site/li/`).

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

### The safety pass (why the optimum is not on the buzzer)

Points are a *step* function of the tier reached, so the search cannot see how
narrowly a tier was held — and on live data it routinely held one by seconds. A
final pass (`optimizer._refine_slack`) therefore picks, from among the many
assignments scoring those same points, the one whose *thinnest* trial has the most
time to spare: it maximises `(total_points, min_margin, sum_margin)` with points
first and compared as exact ints, so **it cannot trade a tier for margin**. On the
2026-07-31 rosters the minimum margin went from 4.28% → 17.92% (SC) and 0.26% —
nine seconds — → 16.41% (LI), for no change in points. `OPT_SLACK_PASS = False` is
the one-line rollback; see `research/risk-aware-objective.md` for the measurements
and for the probabilistic models this deliberately stops short of.

The pass applies to the **unconstrained optimum only** (`optimizer.optimize`, i.e.
`trials.html`). The sign-up plan locks real volunteers into the trials they ticked,
so its margin is not the optimizer's to choose — whatever the sign-ups leave is what
ships. `signup.html` therefore **reports** the margin instead (see below).

## Sign-up optimiser (real sign-ups)

`src/signup.py` reads each guild's sign-up tab (**SC Trial Signup** /
**LI Trial Signup**, see `signup.SIGNUP_TABS`) — that guild's *actual* weekly
volunteers — and builds its `signup.html` + `signup.json`:

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
4. **How safe the lineup is.** Each trial reports when its last tier was *banked*
   (`clear_seconds`) out of the 3600-second budget, and the share of the budget left
   over (`slack_fraction`); the summary strip leads with the **thinnest** of them and
   the comparison table shows the same figures for the optimum, whose margin the
   safety pass maximised. Bands are `config.SLACK_THIN` / `SLACK_OK` (red < 5% ≤
   amber < 15% ≤ green) — display only, nothing optimises against them. A trial that
   banks *no* tier reads "no tier banked" and is excluded from the thinnest-margin
   headline, so "scores nothing" is never mistaken for "held by a hair".
5. **Safety swaps** (`signup._safety_swaps`) — the margin counterpart to step 3.
   A best-improvement search over the same neighbourhood, admitting a move only when
   the points are **exactly** equal *and* the thinnest margin **strictly rises**.
   Both conditions were learned the hard way: ranking points-first merely stops a move
   *costing* a tier (a live probe found one that *gained* one while crashing that
   trial's margin to 0.23%), and accepting any lexicographic gain lets moves through
   on total margin alone (five such moves on SC, every one leaving the thin trial
   untouched). Phase 1 moves only uncommitted members; if that cannot reach
   `SIGNUP_SAFETY_TARGET` — the SC case, where the thin trial was all volunteers —
   phase 2 opens the roster and flags each move as *overrides sign-up*.
   `SIGNUP_SAFETY_ALLOW_OVERRIDES = False` stops after phase 1;
   `SIGNUP_SAFETY_MAX_MOVES` bounds the list. Entries are cumulative and each
   strictly improves on the last, so applying any prefix is valid.

   Measured on the live rosters (2026-07-31), at unchanged points:

   | guild | points | thinnest before | after | moves |
   |---|---|---|---|---|
   | Survey Corps | 4900 (= ceiling) | 1.81% (65s) | 11.56% | 8 (all phase 2) |
   | Lactose lnt. | 4500 | 5.76% (207s) | 15.78% | 5 (3 phase 1) |

Each sign-up tab is `col 0 = User`, then this week's four skilling trials in the
fixed columns B–E (each resolved to its `config.SKILLS` column by header, so
"Alchemy" reads the "Bell Farming" column); columns F onward (the two combat
trials) are ignored by position. Parsing is guarded by the "User" sentinel
(gviz silently serves a different tab on a bad name).

## Deploy (GitHub Actions)

`.github/workflows/deploy.yml` builds and deploys on **every push to `main`**, on a
**daily** schedule, and on manual dispatch, using `uv` (via `astral-sh/setup-uv`,
cached) and the artifact-based Pages flow (`actions/upload-pages-artifact` +
`actions/deploy-pages`).

**Push to `main` is the reliable path** when a refresh is actually needed: it
rebuilds immediately. The cron is best-effort and GitHub defers it under load —
every scheduled run on record has started 2h13m–4h00m late, which is why the cron
asks for 01:00 UTC rather than the hour anyone wants (see the comment in the
workflow). Do not read the cron as a promise of when the site refreshes.

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
