# Guild Skill Register (Survey Corps + Lactose lntolerance)

Static site that mirrors a public Google Sheet skill register for the
Milky Way Idle sub-guilds **Survey Corps** and **Lactose lntolerance**, and
publishes it to GitHub Pages. The build runs the whole pipeline once per guild:
Survey Corps at the site root (`_site/`) and Lactose lntolerance under
`_site/li/` — the two guilds share one spreadsheet (and one weekly trial draw)
but have their own member and sign-up tabs. See `GUILD_SITES` in `src/build.py`.

**The weekly draw** — which four skilling trials the game rolled — is read from the
header row of the tab named by `config.DRAW_SOURCE_TAB` (**SC Trial Signup**), whose
four tick-box columns *are* the draw. That tab is written by the game. It replaced a
read of the hand-maintained **Trial Assignments** tab on 2026-08-14, after the
officers rebuilt that tab for the third time and the parser — which knew both of its
previous shapes — found neither, fell back to `config.TRIAL_SKILLS_CURRENT`, and the
site optimised the wrong four trials for a day behind its "MAY BE STALE" banner.
There is deliberately **no layout fallback** now: the chain of fallbacks across
hand-made shapes is what let a stale draw ship quietly. See the `src/draw.py`
docstring for the full account.

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
   `_site/data.json` — which since 2026-09 also carries this week's assignments
   (see below) — (`src/build.py`) once per guild (Survey Corps at the
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

## Where member data comes from

Every rate in this project is built from five facts about a member: their **skill
level**, their **house room** level for that skill, the **tool** they hold, the
**shrine levels they have bought**, and — since 2026-09-02 — **the rest of their
equipment**. Until 2026-08-31 the first four came from a hand-maintained spreadsheet
tab and three of them were partly guesses; the fifth was not read at all and was
asserted of everybody as a handful of constants. Now they come from a scripted
per-character harvest (`apps-script/profiles/`, written to an **SC Roster** / **LI
Roster** tab and read by `src/roster.py` and `src/gear.py`), with the manual tab as
a per-field fallback.

### The precedence is per FIELD, not per member

```
roster tab   ->  the member's actual level, house room, tool item + its
                 enhancement level, and their five purchased shrine levels
manual tab   ->  whatever the roster did not report: the Tool checkbox, and
                 the skilling Top / Bottom, which the roster does not carry
                 and never will (the upstream module excludes rotating
                 combat slots)
constants    ->  last resort: DEFAULT_HOUSE_LEVEL, the assumed +7 gear,
                 GUILD_SHRINE_LEVELS
```

Per field because that is what the data looks like. **Nine SC and seven LI members
hide their gear** — all twenty tool columns blank, while their levels, houses and
shrines are fully populated — and the right answer for them is *roster for what it
knows, manual for the rest*. A per-member switch would have thrown away real levels
to avoid a missing tool. Every resolution is tagged, the tags are counted into a
`provenance` block in each artefact, and the pages render a mark per member so a
reader can see which of the three tiers their own row came from.

**Five LI members are new.** They exist on the roster with full levels, houses,
shrines and tools, they all signed up for trials, and the manual tab had never heard
of them — the pre-change build log records itself ignoring them by name. They are
now seated (`ROSTER_ADMITS_NEW_MEMBERS`), appended after the manual members in
roster-tab order so the seed-fixed optimizer trajectory stays reproducible. They do
**not** enter `index.html`, which mirrors the officers' own tab and must keep doing
so — that is the page an officer uses to notice the missing row.

### The fifth fact: equipment, read per item

The roster tab carries one further column, `gearSeen`, and it is not like the others.
Every other cell is a **snapshot**; this one is the **union of every capture** of that
member's gear, keyed on item, keeping the higher enhancement level, pooled over months
and across machines. `src/gear.py` reads it against a 39-item catalogue transcribed
from the game's own data.

**What it replaced.** Five constants asserted the same equipment of every member — a
+3 cape, a +7 "family piece", +7 on the skilling top and bottom where ticked, and a
flat 5% gathering-doubling — and a sixth term was not modelled at all: the **neck,
ring and earring slots**, which no source this project read had ever reported. That
omission was the largest single line in the risk budget, worth 0.0081–0.0110 of a
~0.0123 total.

**What the sheet actually said**, pooled over both guilds (202 visible members):

| the model asserted | the union observed |
|---|---|
| a +3 cape, every member, every skill | 97 capes; pooled mean **effective** speed 0.0738 against the assumed 0.0665; 73% refined (★) |
| a +7 family piece, unconditionally | 48% of members show **none** of the four, 37% show **all four**; mean level 4.6–6.3, not 7 |
| nothing in the neck slot | **178 of 202** wear a necklace — 117 Philosopher's, 57 of Speed, 4 of Efficiency |
| a flat 5% gathering doubling | 95 gathering rings, 101 gathering earrings; 34 wear Rare Find instead, which is inert in a race |
| +7 on every piece | grand mean level **5.91** over 1,448 observations; mode 5 |

**The change is, overwhelmingly, the neck slot.** Decomposed per slice, the
accessories move mean speed +0.046 (SC) / +0.041 (LI) and efficiency +0.018 / +0.013,
while the cape (+0.009 / +0.006), the family piece (−0.003 / −0.006 efficiency) and
the garments (~−0.001) are rounding corrections beside it. The net direction is **up**
— which is precisely why the neck was the largest row in the risk budget.

**The ownership rules.** A slot the union read is priced from what it saw, at the
enhancement level it saw. A slot it did not read is treated four different ways, and
the differences are deliberate:

```
cape           assume the skill's covering cape at this guild's POOLED MEAN
               bonus -- one slot can only ever show the one worn, so a
               Gatherer Cape says nothing about the Culinary one
family piece   assume owned, at THAT ITEM's per-guild mean level
top / bottom   owned iff the manual checkbox is ticked OR the union saw it;
               level observed where seen, else the pooled garment mean
neck/ring/ear  ZERO. Never imputed: the Philosopher's pieces are the rarest
               items in the game and must not be assumed onto anybody
```

Two consequences worth stating. A member wearing a **Necklace of Wisdom** or a **Ring
of Rare Find** — 41 of them — scores zero for that slot without needing any special
case: they hold the slot with something inert, and the accessory rule already says
zero. And the **sixteen members who hide their gear are not a special case either**;
they follow the unobserved rules exactly. There is no `hidden` branch anywhere in the
module, which is the single largest simplification in its design.

**The imputation statistics are measured, not transcribed**, and per guild — SC's
family pieces average 1.2–1.5 enhancement levels above LI's, so one shared figure
would misprice both. Unlike the item table, which is a catalogue fact pinned as a
constant, these are live measurements of a changing guild and a written-down value
would be stale the week after. There are three of them rather than one because eight
of the eleven observed garments rest on **n = 1 or n = 2**, and a mean of one
observation is not a mean; garments are therefore pooled, family pieces are per item
(n = 38–50), and capes are pooled as *bonuses* rather than levels because the
plain/★ split gives a pooled level no unambiguous base to apply itself to.

**Two things the column proved in passing.** The union and the roster's existing tool
columns agree on **2,020 of 2,020** observations — same item, same enhancement, no
blanks, no mismatches — which retires `TOOL_ENHANCE_WHEN_UNKNOWN` as demonstrably
never exercised and validates the upstream writer end to end. And the manual top/bot
tick turns out to be a near-perfect **superset** of the sighting: four cases in 1,900
where the union saw a garment nobody had ticked. That is what earns the "ticked **or**
seen" rule, and what makes a garment neither ticked nor seen a claim of *non*-ownership
rather than an unknown.

**One judgement call is recorded rather than settled.** The four family pieces are
held all-or-nothing, and the rotation defence fails: 82 members wear a skilling
necklace — proving the capture caught them in skilling kit — while showing not one of
the four. The universal grant is nevertheless kept, on the operator's judgement that
the union has not yet converged. `GEAR_IMPUTE_FAMILY_PIECE = False` reverses it in one
line, and the slice is small enough that being wrong costs little either way. The
disagreement, and how to settle it in a few weeks, is in
`research/per-item-gear.md` §3.1.

### The switch ladder

Every one of these is a one-line rollback, and each was measured on its own:

| switch | off restores |
|---|---|
| `ROSTER_SOURCE_ENABLED` | the pre-roster build **bit for bit** — no second fetch, no merge, no new JSON keys, no page changes. Pinned by `test_roster_disabled_reproduces_the_golden_week`, which compares a whole week against a golden generated from the pre-change commit. |
| `ROSTER_USE_LEVELS` | the manual tab's levels |
| `ROSTER_USE_HOUSES` | the manual tab's `H` column, then `DEFAULT_HOUSE_LEVEL` |
| `ROSTER_USE_TOOLS` | the manual tab's Tool checkbox at an assumed +7 |
| `ROSTER_USE_TOOL_ENHANCEMENT` | the observed tool tier at the assumed +7 — the targeted partial rollback for the one adverse slice |
| `ROSTER_USE_SHRINES` | the guild-wide shrine read, and `simulate_race`'s once-per-race hoist, bit for bit |
| `ROSTER_ADMITS_NEW_MEMBERS` | "reported, not seated" for the five roster-only LI members |
| `ROSTER_MIN_JOIN_RATE` | below this join rate the roster is **refused** for that guild and every member keeps the manual tab's data. Guards the catastrophic case: gviz serving a different tab past the header guard would otherwise silently reprice a whole guild. |
| `GEAR_SOURCE_ENABLED` | the pre-gear build **bit for bit** — the column is not parsed, nothing is resolved, no new JSON keys, no page change. Pinned by `test_gear_disabled_reproduces_the_golden_week`, which is stronger than a stored golden: the members in it *carry* a full wardrobe, fully resolved, and nothing but the switch stands between that data and the rate. |
| `GEAR_USE_CAPE` / `_FAMILY_PIECE` / `_GARMENTS` / `_ACCESSORIES` | that slice's pre-gear constant, so an adverse slice can be reverted without losing the other three |
| `GEAR_IMPUTE_FAMILY_PIECE` | "own only where seen" — the evidence-led reading of the one judgement call above |
| `GEAR_GATHERING_IN_RATE` | prices every `gatheringQuantity` item at zero, isolating the open question about `doubleProgressChance` **without** also removing the community buff, which the flat constant could not do |
| `GEAR_MIN_IMPUTE_N` | below this many observations an imputation statistic is **refused** and the pre-gear constant is used, because a mean of two observations is worse than the assumption it replaces — it merely *looks* measured |

### The four slices, measured one at a time

Mean change in per-member rate over matched member × drawn skill, each switch flipped
alone. Two independent code paths were compared — a hand-rolled mirror of the rate
model that does not import `src/roster.py`, against `roster.merge` +
`trials._prepare_member` — and they agreed to **0.000pp on every slice**:

| slice | SC | LI | |
|---|---|---|---|
| levels | **+2.539%** | **+6.713%** | the manual tab was simply behind |
| houses | +0.035% | −0.120% | small both ways; LI's blank cells averaged *below* the flat default |
| shrines | +1.444% | +0.954% | the model held everyone at level 1; the real means are 2.99 and 2.30 |
| tools | **−0.211%** | **−0.872%** | **adverse, and this is the point** |
| all four | +3.867% | +6.680% | |

**The adverse slice is the evidence that this is a correction rather than a coat of
optimism.** The tool slice is negative because the model assumed every tool was +7
and most are not. A change that made every number better would be indistinguishable
from a change that made every number bigger; one that makes three better and one
worse, in the directions the data says, is a different kind of claim.

### What it bought — and it was not a tier

| | before | after | |
|---|---|---|---|
| SC step points | 4900 | **4900** | unchanged |
| SC E[points] | 4910.4 | **4926.9** | +16.5 |
| SC thinnest `P(holds)` | 0.9485 | **0.9870** | |
| LI step points | 4600 | **4600** | unchanged |
| LI E[points] | 4592.3 | **4640.8** | +48.5 (of which **+11.0** is the five admitted members) |
| LI thinnest `P(holds)` | **0.5031** | **0.9333** | |

**No tier was gained, on either guild, in any run**, and the implementation plan
predicted otherwise. A ~6.7% rate improvement is nowhere near a tier boundary — the
boundaries are 400 target units per tier level and the parties were mid-ramp, not
near a crossing. The prediction confused "the rate rises a lot" with "the tier
changes", and the ramp/step structure of partial credit is exactly what makes those
two different questions.

**The gain went into safety instead, and it is worth more than a tier.** LI's
thinnest trial had been banking tier 11 on a coin flip: `partial_fraction` 0.0002 —
two ten-thousandths past the boundary — at `P(holds) = 0.5031`. It now holds that
same tier at **0.9333**. Nothing on the page reads differently at a glance; what
changed is that the number is now true.

### Shrines: the guild's level is a CAP, not a gift

Worth stating plainly, because it is the thing a reader will otherwise misread from
`config.GUILD_SHRINE_LEVELS`, and because the model had it wrong for **88–95% of
members**:

> The guild buys the *right* to a shrine level with guild points. Each member then
> spends **their own** resources to actually take it. It is the member's purchase
> that multiplies their stats.

The model held every member at level 1. Measured, SC's members hold force levels 0
through 4 with a mean of 2.99 and LI's 0 through 3 with a mean of 2.30 — a spread
that a guild-wide grant cannot produce. So the rate model reads each member's own
purchased level (`trials.member_shrine_bonuses`), and two page probes read the cap:

- **`probe_shrine_adoption`** — how many members sit *below* the cap the guild has
  already paid for. **54 of 107 on SC, 49 of 105 on LI**, on force. Those members
  can raise their own rate today for **no guild spend whatsoever**. This is the most
  actionable finding of the whole change, and the model could not previously see it
  because it believed everybody was at level 1.
- **`probe_shrine_upgrade`** — what raising the cap buys. **Nothing at all on the
  day it completes**, by construction, because no member's stats change until they
  buy in; and a full-adoption ceiling thereafter that moves only the members already
  at today's cap. Before this change the page reported a payback period for a
  purchase with no immediate effect, and its docstring called that figure a *lower*
  bound.

Two config maps, deliberately, because both are "the guild's shrine levels" in
English and they are not the same number: `GUILD_SHRINE_LEVELS` is the modelled
guild-wide **fallback** for a member whose column is blank (and the switched-off
path), while `GUILD_SHRINE_CAPS` is the per-guild **cap** and feeds the two probes
and nothing in the rate model.

### The risk constant was recalibrated, and it had been stale at deploy time

`config.RISK_SIGMA_SYSTEMATIC` prices what the model does not know: unmodelled
neck / ring / earring gear, enhancement levels away from the assumed +7, mis-ticked
tool checkboxes, house-level slips. Three of those four are now **observed** per
member, so 0.0131 had become a pessimism that was knowingly false — and
`expected_credit_points`, the shipped objective, under-reached because of it.

**It shipped stale, for one deploy cycle, and that is worth admitting rather than
quietly fixing.** The roster flip and the recalibration are two phases, and the flip
went first: the totals above were published against a sigma that still priced three
observed facts as unknowns. Conservative rather than wrong — the live figures were
pessimistic, not falsely reassuring — but stale.

Re-measured at 20 000 replicates on both guilds' shipped plans:
**0.0131 → 0.0123**, traceable to a named row of a published ablation table
(`research/roster-as-primary-source.md` §3). It **shrank but did not vanish**, which
was the prediction recorded before the run: the unrecorded neck slot survives in
full at 0.0081–0.0110 and is on its own larger than everything the recalibration
retired. A sigma near zero would have been a bug — it would mean pretending to know
things that are still unknown.

## Guild Trials optimizer (Phase 2)

`src/trials.py` models each weekly skilling trial as a cumulative tier race and
scores it in guild points; `src/optimizer.py` assigns members across the week's
**4 trials to maximise total points**. The objective is non-linear and
non-separable — it is piecewise linear with a step at every tier boundary, and the
1% per-member headcount penalty means a weak member can *lower* a party's score, so
party size is itself a decision. Every strategy is therefore judged against the
real `simulate_race` oracle (memoised in `AssignmentScorer`).

### Partial-tier credit (game patch 2026-08-11)

The game now credits progress into the tier a party did **not** finish, at half
rate — `0.5% credit per 1% progress` — so a trial is worth
`100 + 100 × (T + 0.5·f)`. Each tier is therefore a **ramp of 50 points followed by
a step of 50** at the boundary: the old 100-point cliff halved, not abolished.

This is the most consequential change the project has absorbed, because the old
cliff is what much of the optimizer was shaped around. Before it, a member who
crossed no threshold was worth *exactly* zero, so a marginal seat was free and
`_fill_bench` could call it "no harm done"; exact integer ties existed in
abundance, which is what let the safety passes promise "the same points". Neither
is true now. `research/risk-aware-objective.md` R1 had written the migration down in
advance and called the smoothing a "happy accident" that would make the existing
search strictly better — which it was: on the live Lactose Intolerance roster the
deterministic total rose **4500 → 4700**, two whole tiers, at the same seed.

`TRIAL_PARTIAL_CREDIT_RATE = 0.0` restores the pre-patch step function bit for bit
(a one-line rollback, pinned by a test). `research/partial-tier-credit.md` carries
the derivation, the measurements and the open questions.

Guild **shrine buffs** now apply inside trials too — Shrine of Force grants
efficiency and Shrine of Tempo action speed, +0.005 per level each; the other three
buff loot and XP and must never touch the rate model. `research/guild-shrines.md`
has the game data, both cost ladders, and the verdict that buildings dominate
shrines as an investment by an order of magnitude.

**Community buffs are levelled, 1–20**, and the magnitudes are confirmed game data
rather than the placeholders they were carried as: gathering `0.20 + 0.005/level`,
enhancing speed `0.20 + 0.005/level`, production efficiency `0.14 + 0.003/level`.
Note that `flatBoost ≠ flatBoostLevelBonus` here, so the `per_level × level`
shortcut the buildings, houses and shrines use does **not** apply — and the old
production figure of `0.15` turned out to be a value the game grants at no level at
all. `research/community-buffs.md` has the dump, the ladder, and the one open
question that would cost 16% of every gathering rate if it goes the wrong way.

### The buff-level selector, and the bound it carries

The site optimises at **level 1** (`config.COMMUNITY_BUFF_LEVEL`; the guild's real
levels are in no capture we hold) and the trials page carries the **whole 1–20
ladder** behind a slider at the top: one optimiser run, re-rated at every rung by
`trials.run_week_ladder` and shipped inline, so moving it recomputes nothing and
fetches nothing.

**Every rung is a lower bound and the page says so.** Re-rating answers *"what would
this week's plan score at level N"*, not *"what is the best plan at level N"* — the
optimiser would seat different members, because a common-mode buff changes who is
worth a seat. That is the same fixed-party bound `probe_building_upgrade` already
publishes, and it is the more operational of the two questions besides: the parties
are settled early in the week, while cowbells can be spent at any hour.

The bound turns out to be **tight, and the whole ladder nearly flat**. Measured on
the 2026-08-14 live rosters:

| | L1 | L20 re-rated | L20 re-optimised | gap |
|---|---|---|---|---|
| Survey Corps | 4,939.9 | 4,961.6 (+21.7) | 4,965.8 | **+4.2** |
| Lactose lnt. | 4,656.8 | 4,679.8 (+23.0) | 4,680.4 | **+0.6** |

Nineteen levels of all three buffs are worth about **0.4%**, and **not one extra
tier** on either roster — the tiers are `10,12,12,11` and `9,11,11,11` at every rung.
Re-optimising on top of that adds four points in five thousand. This discharges the
"price the ladder" question in `research/community-buffs.md` §4 with the same kind of
negative result the shrine payback table produced, and it is why the level-20
**counterfactual page was retired** (`TRIALS_PUBLISH_MAXBUFF_PAGE = False`): it cost
a second complete optimiser run, ~90s a guild, to buy a number the slider now brackets
to within a tenth of a percent. Its path is intact and still tested; `True` restores
it, and the two controls coexist.

What the slider *does* move, and the reason it earns its place, is **safety**. On
2026-08-14 Survey Corps' Enhancing trial banks tier 10 with **0 seconds spare and
holds 50% of the time** at level 1, and with **222 seconds spare, holding > 99.9%**,
at level 20 — a coin flip becoming a certainty, for no change in tier and 6 points.
The chosen level rides in the URL (`#buffs=12`) rather than in localStorage, so it is
shareable and cannot silently persist into next week; off the published level the
summary strip is outlined and captioned to say so.

The shipped default is the ensemble strategy `"best"`
(`config.TRIAL_OPTIMIZER_STRATEGY`): it runs several strong pipelines — including
a **beam-search-seeded genetic algorithm** — and returns the single best result.
`src/optimize_bakeoff.py` is the harness that compared the field (see the
`# BAKE-OFF RESULTS` block in `config.py`). To restore the Phase-1 random split,
set `TRIAL_OPTIMIZER_STRATEGY = "random"` (a one-line rollback).

### The objective is E[points], and that is what took the optimum off the buzzer

**The optimizer maximises the *expected* credit score** —
`trials.expected_credit_points`, the deterministic score integrated over the
calibrated multiplicative shock (`config.OPT_OBJECTIVE = "expected"`;
`"credit"` is the one-line rollback to the deterministic score).

It did not always. The history is worth keeping, because each step was a correction
to the last:

1. **Step objective.** The search could not see how narrowly a tier was held, so a
   final pass (`optimizer._refine_slack`) picked, from among the many assignments
   scoring the same points, the one whose *thinnest* trial had the most time to
   spare. On the 2026-07-31 rosters that lifted the minimum margin from 4.28% →
   17.92% (SC) and 0.26% — nine seconds — to 16.41% (LI), for no change in points.
2. **Partial credit reversed that, deliberately.** Completing a tier is still worth
   a 50-point step, which dwarfs any margin, so the optimizer *reached* for tiers it
   could only just hold — correctly, since falling short no longer forfeits the tier.
   Three of eight trials then banked their tier with 1–4 seconds to spare at
   `P(holds) ≈ 0.51`. The safety pass could not undo it: stepping back to a
   comfortable tier costs ~55 points and `OPT_SLACK_POINTS_TOLERANCE = 0.0` forbids
   spending any.
3. **E[points] as the objective fixes it at the source** (2026-08-14). The
   deterministic score prices a coin-flip tier as a certainty; the expectation does
   not, so the search stops buying tiers it cannot hold — while still reaching
   wherever reaching really does pay, because E prices that correctly too.

`research/partial-tier-credit.md` §9.1 had shipped E[points] as *reporting only*, on
the stated prediction that "optimising it would pick the same parties". **That
prediction is refuted.** Measured on the live 2026-08-14 rosters, same draw, same
seed:

| | objective | banked | credit | **E[points]** | thinnest margin | min `P(holds)` |
|---|---|---|---|---|---|---|
| Survey Corps | credit | 4900 | 4,939.9 | 4,891.3 | **0.01%** | **0.502** |
| Survey Corps | **expected** | 4900 | 4,934.3 | **4,932.7** | **3.44%** | **0.977** |
| Lactose lnt. | credit | 4600 | 4,656.8 | 4,632.5 | **0.01%** | **0.501** |
| Lactose lnt. | **expected** | 4600 | 4,656.1 | **4,656.1** | **6.10%** | **0.999** |

Both guilds bank **exactly the same tiers** and the same step points. What changes is
that four coin-flip trials become near-certainties: SC gains **+41.4 expected points
for 5.6 deterministic ones**, LI **+23.6 for 0.7**. The mechanism is the ramp —
credit is piecewise linear with a 50-point step at each boundary, so a party that has
just crossed one is worth almost nothing extra per unit of rate while one mid-ramp is
worth half a point per 1% of progress; the deterministic score therefore spends rate
where it pays on paper and leaves the just-crossed tier balanced on a coin.

**It costs about 3× per evaluation** — `simulate_race` is 0.145–0.164 ms and
`expected_credit_points` a further 0.269–0.318 ms (an 81-node quadrature plus the
Wald sigma) — so the build's optimise phase goes from ~1m54s to ~5m34s wall. §9.2
already took this position on a smaller version of the same bill: a cost that buys
correctness is worth paying rather than a regression to chase.

The safety pass survives with a narrower job still — the objective is a *sum* over
trials while risk is a *minimum* over them, so it remains the max-min correction to
a max-sum search — but it now finds far less to do, which is the point.
`OPT_OBJECTIVE = "credit"`, `RISK_EXPECTED_POINTS = False` and
`OPT_SLACK_PASS = False` are the respective one-line rollbacks.

Note the consequence for `signup.html`: **its plan totals are now expected points
too**, since they are compared directly against scorer figures. Mixing the two
currencies would leave the page quoting an "enforced → reachable" arithmetic that did
not add up, so `optimizer.objective_of` is the single selector both sides read, and
the deterministic total rides alongside as the ceiling.

The pass applies to the **unconstrained optimum only** (`optimizer.optimize`, i.e.
`trials.html`). The sign-up plan locks real volunteers into the trials they ticked,
so its margin is not the optimizer's to choose — whatever the sign-ups leave is what
ships. `signup.html` therefore **reports** the margin instead (see below).

### Pinned members

Most readers want one fact from `trials.html`: *which trial am I in, and is it
safe?* Everything else on the page is context for that. The ☆ beside any member —
in a roster table, on the bench, or in a search result — pins them to a **Your
members** panel above the fold, which survives the next visit and the next
week's rebuild.

Three decisions worth keeping:

- **Names are stored, never row ids.** The `r-<trial>-<row>` ids are regenerated
  on every build, so a stored id would point at a stranger by Tuesday. A stored
  name either resolves against this week's index or is shown, honestly, as *not on
  this week's page* with its star still there to unpin.
- **The key is namespaced per guild** (`guild-trials.pins.sc` / `guild-trials.pins.li`, carried
  on `#assign-data`'s `data-pin-key`). Both guild sites are served from the one
  `github.io` **origin** — the sub-directory does not separate them — and
  localStorage is per-origin, so a bare key would have the two guilds silently
  overwrite each other. Pinned by the `test_pin_key_is_namespaced_per_guild` test.
- **The panel ships hidden and every star ships hollow.** The page is a static
  file on a CDN and the pins are per-device, so no pin can be known at build time;
  the script fills them in on load. The panel also re-renders when the buff-level
  slider moves — it quotes the trial's score and margin, and those are exactly what
  the slider changes, so a pinned member must never be left reading level 1's
  figures inside a level-20 view.

State lives entirely in the reader's browser — nothing is written to the sheet,
and clearing site data clears the pins.

### data.json carries this week's assignments

`data.json` answers *what does each member have*; `trials.json` answers *what is
each member doing this week*. A reader who wanted both fetched both and then walked
four party rosters, which is one request more than an in-game userscript has to
spend. So `data.json` now also carries a **projection** of the week — never a copy:
no rates, tools, timelines or probes. `trials.json` is unchanged and remains the
full record.

Two additions, both gated on `config.REGISTER_CARRIES_WEEK`:

- A top-level **`week`** object: `generated_at`, `week_date`, `skills`,
  `draw_stale`, `draw_warning`, `community_buff_level`, `total_points`,
  `total_credit_points`, `parties` (each `skill`, `party_size`, `tier_reached`,
  `points`, `credit_points`, `clear_probability`, `members` as a name list),
  `bench`, `not_on_register` and `unassigned`.
- A **`trial`** stamp on every member: `{"skill": …, "status": …}`, where `status`
  is `assigned`, `bench` or `unassigned` and `skill` is `null` unless assigned.

The consumer recipe:

```js
const m = data.members.find(m => m.name === me);
m?.trial?.skill                       // the skill, or null
data.week.draw_stale                  // whether the draw was a fallback
data.week.generated_at                // equal to trials.json's when both are one build
```

Three caveats worth stating plainly:

- **`week_date` is the *build* date**, not a cycle id — the draw source publishes no
  cycle date. To know whether the block is current, compare `generated_at` with
  `trials.json`'s; equal means the two files are one build.
- **`member_count` is the register's count, not the seat count.** Roster-only members
  are seated but have no register row (`index.html` mirrors the officers' tab), so
  they are named in `week.not_on_register` instead — look them up in
  `week.parties[*].members`. The seat count is `sum(party_size) + len(bench)`.
- **Every existing key is unchanged** in name, type, order and value; `week` and
  `members[i].trial` are the only additions.

Setting `config.REGISTER_CARRIES_WEEK = False` is the one-line rollback: no `week`
key, no `trial` keys, no `Trial` column, and `data.json`'s key set exactly as it was.

### Combat seats on the trials page

`trials.html` is the skilling page, and it was the *only* page — combat was read,
parsed, published into `trials.json` and rendered nowhere. A member who wanted to
know which combat team they were in had to open the spreadsheet or install the
in-game userscript. Since 2026-09-18 the **search panel** and the **pinned-members
panel** answer it:

```
[ ☆ ]  CCTV3          Cooking
       banked at 2840s · level 94
       ── Combat ──────────────
       Hedgehog · SC Team 1
       cursed 1 · "Cursed"
```

The quoted label is the optimiser's **recommended loadout**, by the template's own
curated name — `Fire DPS (Blazing)`, not a titlecased role. It arrives on the tenth
column of the Combat Teams tab (`Loadout Name`) and rides on each seat as
`loadout_name`. A seat read off a **nine-wide** tab has no label and the block shows
one line instead of two; `""` is the only degradation there is, and it is never
guessed at from `role`.

Four decisions worth keeping:

- **The combat fields ride inside the existing `#assign-data` island**, on the
  entries that already exist, under two-character keys prefixed `c` (`cb`oss,
  `ct`eam, `cs`lot, `cl`oadout). The whole index ships inline in every page, so
  `"loadout_name"` spelled out once per seat on a hundred members is kilobytes.
  There is **no second island, no second `JSON.parse`, no new fetch and no new
  global** — `_TRIALS_JS` still depends only on `#assign-data` and `data-*`.
- **A member with no combat seat carries no combat keys at all**, rather than four
  empty ones. `if (h.cb)` then means "this member has a combat seat", where
  `h.cb === ""` would mean "has a seat with no boss", which is not a state that
  exists. `cl` is omitted independently, for the nine-wide case above.
- **A combat-only member is appended to the index**, as `"t": "Combat only"` with
  `"r": ""`. Someone seated in combat who is on no skilling roster and not on the
  bench used to search their own name and be told *No member matches that name* —
  a lie about somebody very much on this week's page. `"r": ""` is honest: there is
  no roster row to jump to, and both jump affordances are guarded on it.
- **`combat.available: false` is said, not swallowed**, once at the top of each
  panel with the reason verbatim. `build._fetch_combat` degrades to that on any
  failure and never stops the deploy, so a page that simply showed nothing would
  tell a member their guild had not assigned them when the truth is that the page
  could not read the tab.

`signup.html` is deliberately **unchanged**. `_render_signup_html` takes the *plan*
dict; the combat block is attached to the *week* dict and to nothing else, so giving
it combat would mean threading a second argument in or attaching the block to a
second dict — and a second place for the same fact is a second place to drift. The
two pages also answer different questions: `trials.html` says *where am I this
week*, `signup.html` says *did I sign up for the right thing*.

**Follow-up, wanted and not built: combat team cards and seat tables.** The whole
roster of each combat party, rendered the way the skilling parties are. The reason
it is not here is that the search-and-pin panels already answer *where am I* for
every member at a fraction of the page weight, and that is the question that was
actually being asked. Equipment rendering is further out still and is explicitly
not wanted yet.

## Sign-up optimiser (real sign-ups)

`src/signup.py` reads each guild's sign-up tab (**SC Trial Signup** /
**LI Trial Signup**, see `signup.SIGNUP_TABS`) — that guild's *actual* weekly
volunteers — and builds its `signup.html` + `signup.json`:

> **The plan is withheld when a guild's tab is a week behind.** The game refreshes
> each guild's sign-up tab when a new cycle opens, and not for both guilds at once.
> On 2026-08-14 the LI tab still held the entire 8/10 cycle — its four skills *and*
> both its combat bosses — while SC's had moved on. Nothing noticed, because all four
> of last week's headers are perfectly valid skills. `build._fetch_guild` now compares
> each guild's four sign-up columns against the draw and emits the inactive
> placeholder instead of a plan when they disagree: advice built from the wrong week's
> volunteers is indistinguishable from good advice, which makes it worse than none.
> It returns by itself once the tab catches up.

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

The schedule is daily rather than hourly because the **inputs** move daily at most —
the draw is weekly and the member data is slow. It is *not* an Actions-minutes
economy: this repository is public, and public repositories get standard
GitHub-hosted runners free and unlimited (4-vCPU/16 GiB at that). The
"~2000 minutes/month" figure this section used to cite never applied here.

### Where the run time goes

The three jobs are `test` and `build` **in parallel**, then `deploy` gated on both.
The gate is on publishing, not on building — `deploy-pages` is the only step that
makes anything public — so a red suite still ships nothing while the two jobs share
the clock instead of queueing.

`build` runs the independent optimiser units concurrently in separate processes — one
per guild as shipped, two per guild with the counterfactual switched back on; see the
long note above `build._GuildInputs`.

**Re-measured 2026-09-02** (Apple Silicon, four restarts, `OPT_OBJECTIVE =
"expected"`), replacing a table taken on 2026-08-14 that had gone badly stale:

| | measured | the 2026-08-14 table said |
|---|---|---|
| one `choose_assignment`, SC | **424–454s** (five runs) | 84.8s |
| one `choose_assignment`, LI | **381–386s** (three runs) | 56.2s |
| **the whole `python -m src.build`** | **503.6s** (8m 24s) | ~103s critical path |
| the full test suite | **482–485s** (8m 2s) | not measured |
| σ campaign, 20 000 reps with ablation | **~130s per guild** | not measured |

**A 5–7× regression, and it was `OPT_OBJECTIVE = "expected"`** — exactly as the
previous version of this section suspected but could not confirm. The expected
objective calls `trials.clear_sigma` and `_cumulative_tier_times` inside *every*
objective evaluation, of which the search makes ~87 000. Nobody had noticed because
the only thing that ever runs a full search is CI, where the cost shows up as
nothing but a slower green tick.

Two honest caveats on that table. The per-search figures are `trials.choose_assignment`
called directly, so they exclude the fetch (~1s) and the scoring pass (which is
cheap — `score_assignment` alone, no search). And **`signup.plan` and the buff
ladder were not separately re-instrumented**: the build's 503.6s minus SC's ~440s
search leaves ~60s for the sign-up plan, the ladder and all rendering, which is
consistent with the old 18.6s + 0.20s having grown by a similar factor, but that is
an inference and not a measurement. The claim that the counterfactual is the
*dearer* run is unaffected, since both runs got slower together.

The output is byte-identical either way: every seed is fixed and no unit reads
another's state. `config.BUILD_PARALLEL = False` runs the same units serially in one
process when a traceback needs reading in peace.

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
