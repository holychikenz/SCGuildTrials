# Implementation plan — the full roster allocation: every eligible member seated to `partyCap`, and the whole allocation published

**ResearchPack:** `scratchpad/fills-research.md` (418 lines), read in full. Everything above
its CORRECTION section that derives team rosters from the SIGN-UP SHEET is void, as it says;
the size survey and the endpoint/reader facts survive and were re-verified here. The three
DECISIONS (D1–D3) and the seven items under "WHAT D1 DRAGS IN" are the brief. No external
library is involved, so there is no version to pin — the research is the two codebases and
this plan re-verified every line it intends to edit. **Anchors:** `farm/guild` at `086de16`
(dirty: `src/build.py`, `src/config.py`, `src/trials.py`, `tests/test_trials.py`, `README.md`,
`research/*`, `.claude/plans/guild-trials-2026-08-patch-implementation-plan.md`; untracked
`src/buildings.py`, `tests/test_build.py`, `tests/test_buildings.py`,
`tests/test_register_week.py`, two plans); `SCLIRoster` at `fab85ab` (dirty: `README.md`,
`apps-script/Code.gs`, `apps-script/README.md`, `data/templates/dps_water.json`,
`optimizer/README.md`, `optimizer/cli.js`, `optimizer/src/report/render.js`,
`optimizer/src/sources/credentials.js`, `optimizer/test/credentials.test.js`,
`optimizer/test/pins-writeback.test.js`, `plan-implementation.md`, `plan.md`,
`research/armory/icon-map.json`, `scli-roster.user.js`; untracked `optimizer/src/publish/`,
`optimizer/test/combat-tab.test.js`, `test/combat.test.js` — today's combat-glow work, not
yet committed). Line numbers below are the working trees' as of 2026-09-09 evening.
**Baselines (from the session, not re-run here):** farm/guild
`uv run --extra dev python -m pytest tests/ -q` → 479 passed in 7m36s; SCLIRoster `npm test`
→ 987 tests, 986 pass, 1 pre-existing unrelated failure
(`optimizer/test/blast-radius.test.js:46-47`, a byte-check on the dirty
`apps-script/Code.gs`). **Precedent:** `combat-trial-glow-implementation-plan.md` (today)
for the shape; `cli.js:1590` (`--optimize` implies `--simulate`) for the flag implication;
`search.test.js:402-417` for pinning a CLI rule in source.

---

## 1. What changes, in one paragraph

Today `node optimizer/cli.js report --guild sc --publish-combat` publishes the exactly-solved
assignment against the officers' **16-seat** composition — `doAssign` derives it from the
`Trial Assignments` pins by counting named columns (`compositionFromPins`,
`candidate.js:203-247`) and only ever shrinks it (`fitToPool`, `:262`); the Hungarian matrix
is then padded to the pool with team-less bench columns (`assign.js:209-212`) and 77 of 109
members land there, `holychikenz` among them. The search that already designs whole
compositions to `partyCap` — `roundZero` → `shapeFor` (`composition.js:465-479`, `:348-379`)
seeded by `dpsWeightsFromLevels` (`cli.js:1161-1167`), which on 2026-09-07 produced 52 + 52
seats and beat the incumbent by +10.33 tiers (`data/exports/run-2026-09-07d`) — runs only
under `--optimize`, which the weekly command does not pass. After this change **a publish is
a search**: `--publish-combat` implies `--optimize` exactly as `--optimize` implies
`--simulate` (`cli.js:1590`), `--no-optimize` is the waiver and the one-flag rollback; the
officers' tab stops being the structural input and stays the **pins** input, merged over the
optimiser's own previous recommendation (written back by `--write-pins`) so that all ~104
seated members carry week-to-week continuity and the incumbent from week 2 onward is last
week's *published* allocation rather than the officers' core; a stub template degrades the
weekly run to that pins composition and says so instead of stopping it; the client timeout on
the one sheet write rises from 20 s to 90 s and an abort is reported as **UNKNOWN**, naming
the tab to check, never as "Nothing was written"; `data/guild.json`'s four stale
`cycle.trials` lines are corrected and its resolution mechanism left alone. Nothing in the
seven-column sheet contract, `trials.json["combat"]`, the Apps Script endpoint, the farm/guild
reader, the userscript or `assign.js` changes. Only seated members are published (D3); the
sheet grows from 32 to ~104 rows (SC) and 29 to ~96 (LI), and `holychikenz` appears with a
real templated `Role`.

## 2. The facts the plan rests on (all verified), and where the ResearchPack was wrong

| Claim in the ResearchPack | What the source actually says |
|---|---|
| The optimiser's files are `optimizer/src/cli.js`, `optimizer/src/assign.js`, `optimizer/src/candidate.js`, `optimizer/src/composition.js`, `optimizer/src/templates.js`, `optimizer/src/trialAssignments.js`, `optimizer/src/styleSeed.js`, `optimizer/src/fitness.js`, `optimizer/src/member.js`, `optimizer/src/trialSignup.js` | **Every one of these paths is wrong in kind**, though the line numbers within them are mostly right. The CLI is `optimizer/cli.js` (3175 lines; there is no `src/cli.js`). The rest sit under `optimizer/src/{optimize,model,sources}/`: `optimize/assign.js`, `optimize/candidate.js`, `optimize/composition.js`, `optimize/styleSeed.js`, `optimize/fitness.js`, `optimize/pins.js`, `optimize/search.js`, `optimize/budget.js`; `model/templates.js`, `model/member.js`; `sources/trialAssignments.js`, `sources/trialSignup.js`. Every citation below uses the real path. |
| `combatTab.js:139` `timeoutMs = 20_000`; `:153` `signal: AbortSignal.timeout(timeoutMs)`; `:143` `const payload = JSON.stringify(...)` | `:139` and `:153` confirmed. The `payload` line is **`:146`**. The abort branch is `:158-163`, and it conflates two names — `err?.name === 'TimeoutError' \|\| err?.name === 'AbortError'` at `:159` — then appends `Nothing was written.` at `:162` for both. `HEADER` is `:38-39`; `combatRowsFromAssignment` `:76-91` iterates `assignResult.assignments` only, so benched members are already excluded (D3 needs no change here). |
| `benchStability` is `assign.js:216-219`; `roleStability`'s `sigma_team` is `:170-180` | **Both drift.** `benchStability` is `optimize/assign.js:168-171`; `roleStability` is `:124-166` with the team term at `:143` (`p.team !== col.team ? s.team : 0`). `roleColumns` `:196-214` confirmed, bench padding `:210-212`; the bench skip in the cost loop is `:264-268` and the `measuredWeaponless` → `INFEASIBLE` cell `:273-276`. `assignRoles` `:216` refuses `seats > rows.length` by name (`:222-231`). |
| `compositionFromPins` is `candidate.js:203-247`, skipping aura `:216`, empty `:230`, `role: null` `:231`; `fitToPool` `:263-264` | Confirmed at `optimize/candidate.js:203-247`, `:216`, `:230`, `:231`. `fitToPool` starts at **`:262`** and caps first (`:270-276`). |
| `DPS_ROLES` `composition.js:139`; `shapeFor` `:348-379`; `splitLadder` `:394-436`; `roundZero` `:465-479` | All confirmed at `optimize/composition.js`. `SPLIT_SHIFTS` is `:230`; `splitLadder` targets `min(pool, teams * partyCap)` at `:400`, which is 104 for SC. |
| `pickTemplate` throws on an unknown role at `templates.js:654-662` | Confirmed at `model/templates.js:654-662`. **Not cited but load-bearing:** `assertSearchable` `:697-714` is the stub gate, message `refusing to search: … still status "stub" …`; `ROLES` is `:118`. |
| The `Melee (Flex)` `role: null` row is `trialAssignments.js:135-137`; `priority` is "read and reported, never obeyed" at `:214-215`; `parseSplit` `:217-260` | Confirmed at `sources/trialAssignments.js:135-136`, `:214-215`, `:217-260`. Pinned by `trial-assignments.test.js:345-351`. |
| `styleSeed.js:22-28` argmax; `dpsWeightsFromLevels` `:151`; `fitness()` `fitness.js:339`; `LEVEL_KEYS` `member.js:28-29`; standing order `trialSignup.js:27-42` | All confirmed at the real paths. |
| `doAssign`'s default construction is "~`cli.js:762-790`" | `optimizer/cli.js:763-790`: `compositionFromPins` `:765`, `fitToPool` `:779`, `makeCandidate` `:781`. Pins are resolved at `:709-713` (`resolvePinsFor`), the eligible pool at `:718-719`. |
| `doOptimize` seeds weights at `cli.js:1161-1166` | `:1161-1167` confirmed. The incumbent is built at `:1170-1200` from the same `compositionFromPins`, `fitToPool`'d; `search()` is called `:1202-1236` with `budgetMs: parseDuration(opts.budget)` (`:1222`, default `DEFAULT_BUDGET_MS = 20 min`, `config.js:96`) and `rateFile: RATE_FILE` (`:1228`). |
| The stub refusal is `cli.js:1546-1550` | **Wrong.** `:1546-1564` is `doReport`'s doc comment ("THREE MODES"). The gate is `:1087-1094` inside `doOptimize` — `assertSearchable(templates, [...needed].sort())` over every role in `ROLES` — and it throws, which `main` turns into `sayRefusal('report', err)` and exit 1 at `:3106-3108`. |
| The winner ships only if it beats the incumbent, `cli.js:1576-1583` | `:1576-1587`: `if (opts.optimize) { search = await doOptimize(...); const pick = search.improved && search.winner ? search.winner : search.incumbent; …}` with the two notes at `:1581-1586`. `improved` is decided in `optimize/search.js:775-778` (`delta > 0 && !isTie`), returned `:819-826`; `search()` refuses without an incumbent `:512-516`; the confirm is TRIMMED, not skipped, when the budget cannot afford it `:745-757`. |
| `resolveTeamTrials` is `cli.js:2518-2540`; `orderBySplit` `:2447`; the last-resort note `:2416` | `resolveTeamTrials` is **`:2484-2585`** (the `Trial Signup` branch `:2519-2543`, `disagreements` `:2392-2400`); `orderBySplit` `:2447` and `:2416` confirmed. It reads `(cfg.cycle.trials \|\| {})` at `:2491`, so the key may be absent. |
| `data/guild.json` `partyCap` SC `:115`, LI `:154`; `cycle.trials` names four stale bosses | Confirmed. `cycle` is `:167-183`; the four lines are `:171-174`. `guildConfig.js` (42 lines) validates only `schemaVersion` (`:22`); `seedPins` reads `(opts.trials \|\| {})` (`pins.js:142`), `doExportRoster` `(cfg.cycle.trials \|\| {})` (`cli.js:583`) — dropping the key would be load-safe. |
| `data/templates/` holds "12 roles, all status transcribed, none a stub" — then lists 13 names | **13** JSON files, all `"status": "transcribed"` (verified by grep): cursed, dps_bulwark, dps_fire, dps_nature, dps_ranged, dps_smash, dps_water, healer_blooming, magic_debuff, magic_support_blooming, regal, stab_debuff, tank. The ResearchPack's count is off by one; its list is right. |
| `Code.gs:112` `MIN_COLS`, `:137-139` header check, `:152-156` width check, `:178-190` clear-and-write; no row cap | All confirmed in `farm/guild/apps-script/Code.gs`; `clearRows` `:180`, `clearCols` `:188`, `clearContent`/`setValues` `:189-190`. |
| `combat.py:117-119` `CombatSeat`; `:314-360` groups on `(hrid, team)`; `:328-340` blank name; `:342-349` hrid guard; `:258-280` guild id; `config.py:1701-1709`, `:91` | All confirmed. Column indices are fixed constants `combat.py:86-92`; the header guard iterates `COMBAT_SENTINEL_HEADERS` (`:236`) — cells 0–6 only — so an eighth column would be ignored (ruling g). `tests/test_combat.py` has 15 tests, none asserting a seat count. |
| The live report: pool 109, `partyCap` 52, `seatsWanted` 104, `binding: "composition"`, `teams[0].roles` sums to 16, `benched: 77` | Confirmed from `data/exports/report-sc-2026-W36.json` (generated 2026-09-09T16:21:56Z, no search, `verdict: null`, `pinStats {pinnedTotal 32, pinnedSeated 26, unpinnedSeated 6}`). `data/exports/combat-sc-2026-W36.json`: 32 rows, `unnamed: []`, no `holychik`. |
| "The search picks the full allocation; the solver needs no change" | Confirmed in kind AND in fact: **`data/exports/run-2026-09-07d/report-sc-2026-W36.json`** is a `report --optimize --include-names` run over this same pool: `SC Team 1` 52 seats (`tank 2, healer_blooming 3, cursed 2, regal 3, stab_debuff 1, magic_support_blooming 2, dps_smash 6, dps_ranged 6, dps_water 14, dps_nature 13`), `SC Team 2` 52 (`… magic_debuff 3, stab_debuff 3, magic_support_blooming 3, dps_smash 11, dps_ranged 9, dps_water 8, dps_nature 4`), benched 5, infeasible 0, `improved: true`, Δ +10.33 tiers. The mechanism exists; the weekly command does not take it. |
| *(not in the ResearchPack)* what "the incumbent" is today | `compositionFromPins` over `resolvePinsFor`'s pins, `fitToPool`'d (`cli.js:1170-1200`). `resolvePinsFor` (`optimize/pins.js:210-240`) **prefers the tab whenever it parses** (`:214-217`) and reads `data/pins.json` only when it does not (`:219-239`). So while officers keep the tab, the incumbent is their 16 + 16 core forever, and `report --write-pins` (`cli.js:1835-1852`) writes a file nothing reads. |
| *(not in the ResearchPack)* `data/pins.json` | **Tracked** (committed at `14b6117`), **SYNTHETIC**: `source: "optimizer/test/fixtures/trial-assignments.csv (SYNTHETIC — see _comment)"`, cycle `2026-W35`, NATO-letter names, ids 1000–1019, 21 slots per team. `pins.test.js:294-317` pins that it says so (`assert.match(body.source, /SYNTHETIC/)`). The first real `--write-pins` archives it as `data/pins.2026-W35.json` (`writePinsBack` `:340-347`) and **breaks that test**. |
| *(not in the ResearchPack)* the measured wall clock of a full-size search | `run-2026-09-07d` `verdict.budget`: `elapsedMs 798073` (**13.3 min**) of a 90-min budget, pool 13 workers, `206.8 ms` per player-iteration of pool time, 17% parallel efficiency; rounds 0 (5 candidates), 1b (28), 2 (21), 2b (19) ran and the confirm at 12 iterations; **round 1 (73 candidates) was SKIPPED**, estimated at 4082 s. The `run-…-fast` variant (1 iteration) took 96 s and ran rounds 0 and 2b only. `run-2026-09-07c` (old depths 8/8) ran 2379 s over a 1200 s budget. **`data/cache/sim/rate.json` no longer exists**, so the next run calibrates from scratch (`search.js:588-620`). |
| *(not in the ResearchPack)* the timeout test | `combat-tab.test.js:323-334` asserts `/did not answer within 20s/` **and `/Nothing was written/`** for a `TimeoutError`. It must change. No test covers `AbortError` by name. |
| `blast-radius.test.js:47` is the pre-existing failure | `:46-47` — `apps-script/Code.gs — the WRITE endpoint — is byte-identical to HEAD`, SCLIRoster's **own** endpoint, dirty since the buildings work. Unrelated; stays red until that file is committed. |

## 3. The design decisions worth arguing

### 3.1 D1, as mechanism: a publish IS a search — `--publish-combat` implies `--optimize`; `--no-optimize` waives it

The search already does what D1 asks (§2, the 09-07d row). What is missing is that the
weekly command never invokes it. Three ways to make the search the weekly path:

1. **Documentation only** — the weekly command becomes `report --optimize --publish-combat`.
   Zero code. Rejected: the operator's existing habit (`report --publish-combat`) would then
   silently publish the officers' 32-row core, which is the exact thing D1 rejects, and the
   sheet is what members act on.
2. **Grow `doAssign`'s default** via `shapeFor(shapeOf(derived), partyCap)` in place of
   `fitToPool`. Rejected by the user in D1 by name: that is "the officers' 16-seat named core
   with only the DPS remainder absorbing the slack" — tanks and healers would stay at 2 and 3.
3. **Imply the search from the publish**, in `doReport` where `--optimize` already implies
   `--simulate` (`cli.js:1590`, `wantSim`). One line, same precedent, habit-safe. A
   `--no-optimize` flag is the explicit waiver (needed for the rollback, §10, and for a
   deliberate re-publish of the pins composition). Chosen.

`--publish-combat=preview` implies the search too: the rehearsal must be the same block the
live run would post.

### 3.2 D2: team targeting stays with `fitness()` and `dpsWeightsFromLevels`

No change. Each DPS seat is a real template with real gear requirements (`DPS_ROLES`,
`composition.js:139`), so `fitness()` (`fitness.js:339`) places mages on magic seats and melee
on melee seats of its own accord, and the per-team mix comes from the guild's own levels
(`cli.js:1161-1167`). `banner.priority` remains parsed and displayed
(`trialAssignments.js:214-215`, pinned at `trial-assignments.test.js:345-351`). Rejected, as
the user recorded it: skewing each team's DPS mix by the officers' free-text Priority cell.

### 3.3 D3: only seated members are published; the known gap is stated, not papered over

`combatRowsFromAssignment` (`combatTab.js:76-91`) walks `assignResult.assignments` only;
`benched` and `infeasible` (`assign.js:807-811`) never reach a row. No reader change, no
contract change. Rejected, as the user recorded it: publishing benched or infeasible members
with a sentinel hrid (`combat.py:342-349` would refuse it, and the userscript would derive a
tile key matching no tile). **Accepted cost, plainly:** a member with no row cannot tell
"benched this week" from "the artefact is stale". Follow-up candidate, out of scope: an
eighth column or a `bench` block; the contract is growable (§3.9).

### 3.4 Rulings (a) and (b) together: the officers' tab is pins-only and is **merged over the optimiser's own previous recommendation**; the incumbent becomes last week's published allocation

**(a)** The tab stops supplying structure and keeps supplying pins. `resolvePinsFor`'s
preference for the tab (`pins.js:214-217`) stands, so `roleStability`'s `sigma_team`
(`assign.js:143`) and `benchStability` (`:168-171`) keep biasing the 32 members the officers
named toward last week's team and seat. That alone leaves the other ~72 seated members with
no pin at all — every one of them "newly seated" each week (`report-sc-2026-W36.md:136`: "6
seated member(s) held no pin"; at 104 seats it would read 72) and free to swap teams whenever
a level changes. That is the churn the user warns of.

**The ruling:** `resolvePinsFor` gains an optional `knownIds` set and, when the tab parses,
**also** reads `data/pins.json` and carries in every slot whose member (i) is in this run's
roster, (ii) is *not* named anywhere on the tab, and (iii) comes from a file the optimiser
itself wrote (`source` starting `optimizer@`, which both `assign --write-pins` `cli.js:800` and
`report --write-pins` `:1845` stamp). Wherever the tab names a member, the tab's pin is the
only one kept — the officers win, as "a pin is a bias and never a constraint" already
requires. The weekly command adds `--write-pins`, so from week 2 the file holds last week's
full recommendation (`pinsFromAssignment` `pins.js:264-306` writes every seated member and
every aura carrier; the round-trip is pinned at `pins-writeback.test.js:279-306`).

**(b)** The incumbent keeps its mechanical definition — `compositionFromPins` over this run's
pins, fitted to this week's pool (`cli.js:1170-1200`) — and with merged pins its *meaning*
becomes: **week 1**, the officers' 16 + 16 core (a floor: the full allocation must beat the
core alone, which any round-0 candidate will, so `improved` is trivially true and the report
says so); **week 2 onward**, last week's *published* allocation minus anyone who left — a
like-for-like "did this week's shape beat last week's on this week's pool", which is what
`search.js:775-778`'s verdict was designed to answer. `pinStats.pinnedTotal` (`assign.js:807`)
rises from 32 to ~104 and the report's "What changed from last week" (`render.js:1396`)
becomes a whole-roster statement.

Rejected alternatives, one line each: **no merge** — keeps the code untouched but accepts 72
unpinned members and an incumbent that is forever a third the size of every candidate;
**prefer the disk file over the tab** when it is the optimiser's — cleaner (b), but drops the
officers' pins entirely, which (a) forbids; **a `--pins-from` switch** — a knob nobody asked
for. The merge is ~35 lines in one function, backward compatible (no `knownIds` → no merge →
every existing test unchanged), and it is the one change that answers (a) and (b) and the
churn risk together.

Two guards are load-bearing: `knownIds` excludes the synthetic ids 1000–1019 in today's
tracked file (and any member who has left), so the incumbent is never inflated by phantom
seats — `compositionFromPins` counts any slot with a `nameAsWritten` and a `role`
(`candidate.js:230-233`); and the `optimizer@` prefix excludes a hand-seeded or fixture file
outright.

### 3.5 Ruling (c): a stub template degrades the weekly run to the pins composition, loudly — it does not stop it

`assertSearchable` (`templates.js:697-714`) throws inside `doOptimize` (`cli.js:1087-1094`);
under `report --optimize` that is `sayRefusal` and exit 1 (`:3106-3108`), so a single
`"status": "stub"` on a Tuesday would leave the sheet untouched. All 13 templates are
transcribed today, so this is latent — but the moment it fires, no member gets a row.

**Ruling:** `doReport` runs the same check *before* calling `doOptimize`, over `a.templates`
and `ROLES` (both already imported, `cli.js:56`). On a stub it pushes a note that names the
template and says THE SEARCH DID NOT RUN, sets `search = null`, and continues with the pins
composition — which from week 2 is last week's full allocation re-solved on this week's pool
(§3.4), and in week 1 the officers' core. The publish goes ahead and `reportReport` prints the
seat count against `seatsWanted` with a WARNING when short (§3.6's print). Any other error
from the gate propagates as today.

Why fall back rather than refuse: `report` already runs and publishes on stubs today, by
design (`cli.js:2874-2876`, README `:119-121`: "the one command that works on stub templates
on purpose"); the refusal was only ever the *search's*. A degraded week with last week's
shape is a member-visible statement; a refused week is a stale sheet that farm/guild marks
`available: false` only if the boss pair has moved. Rejected: refusing (the conservative
reading of "a roster built on a placeholder is a fiction" — but the fallback is not built on
the placeholder; the search is what would have been).

### 3.6 Ruling (d): the wall clock, measured, and what the default budget buys

**Measured** (§2): one full-size `report --optimize` at 104 seats took **13.3 minutes** of
search wall clock on 2026-09-07 with rounds 0, 1b, 2, 2b and a 12-iteration confirm, under a
90-minute budget, on 13 workers at 206.8 ms per player-iteration of pool time. Round 1 —
tanks and healers, 73 candidates — was skipped by the budget's own estimate of 68 min.
**That estimate has never been tested at this size** and was made against a prior-weighted
rate (`priorUsed: true`); the earlier 09-07c run measured 44.6 ms per player-iteration on the
same machine. So the honest statement is: rounds 0/1b/2/2b cost ~13 min; round 1 costs
somewhere between 15 and 70 min; the confirm reserve at 104 + 104 + incumbent × 12 iterations
is 23–30 min by the budget's arithmetic and was largely a cache hit on 09-07d.

**Consequence for D1:** at the default `--budget 20m` (`config.js:96`), the budget will run
round 0 (which fixes the split at 52/52 and fills DPS around the *incumbent's* tank/healer/
support counts — `shapeFor`), TRIM the confirm (`search.js:745-757`) and skip most of 1/1b/2.
Tanks and healers then stay at the officers' counts. D1's "tanks, healers, support AND dps all
scale" is round 1's job, so **the weekly command passes `--budget 90m`** — the budget the one
measured run had — and step 15 records the real figure. A `--budget 5m` re-publish (round 0 +
trimmed confirm) is the fast path when only the seating, not the shape, needs redoing; the
simulation cache (`search.js`, "§2.8") makes a same-week re-run nearly free.

**Variability:** the old default path was deterministic. The search is deterministic *given*
the same inputs, seeds (`seedBase` 1) and budget outcome; what varies week to week is which
rounds fit (machine load, prior rate) and therefore which composition wins. Mitigations: a
fixed budget on the weekly command; the persisted rate (`RATE_FILE`) so estimates settle;
the tie-break that prefers fewer moves (`search.test.js:278`); and the pins merge (§3.4),
which biases the seating toward last week even when the composition shifts by a seat or two.

### 3.7 Ruling (e): the 20 s timeout rises to 90 s, and an abort is UNKNOWN, naming the tab

`postCombatTab`'s `timeoutMs = 20_000` (`combatTab.js:139`) fired today on 29 rows after
Apps Script had, in fact, written them (stamped 16:22:10.646Z), and the message said
`Nothing was written` (`:162`). A client that stopped waiting has learnt nothing about the
server. **Ruling:** default `90_000` — Apps Script web apps may run for minutes and a
clear-and-rewrite of 105 × 7 cells under a cold start and a 302 is seconds, not tens of
seconds, so 90 s bounds the wait without pretending to know the outcome; the abort branch
(`:159-162`, both `TimeoutError` and `AbortError`) says THE OUTCOME IS UNKNOWN, names the tab
(`tab` is in scope) and the `Generated At` stamp to look for (`rows[0][6]`), and never says
"nothing was written". The non-abort branch (`could not be reached`) keeps `Nothing was
written.` — a connection refusal is knowledge. Rejected: retrying on abort (a second POST
after a first that may have landed is a double write racing itself; the endpoint's
clear-and-rewrite makes it idempotent, but the operator should decide, not the client).

### 3.8 Ruling (f): `data/guild.json` `cycle.trials` is corrected, not dropped; the mechanism is untouched

Resolved this session as not-a-bug: it is source 4 of 4 ("the last resort", `cli.js:2416`),
its staleness is detected and printed (`report-sc-2026-W36.md:142`), and the team → boss
*order* comes from `orderBySplit` (`:2447`) over the officers' `banner.split`. **Ruling:**
edit the four values at `data/guild.json:171-174` to this cycle's truth (`badger`, `swarm`,
`badger`, `swarm`) so the DISAGREES note disappears this week; leave `resolveTeamTrials`,
`orderBySplit` and `disagreements` alone; keep the file (it carries `partyCap`, `partyMin`,
`tabs`, `buildingLevels`, `shrineLevels`, `auraOrder`, `buildersHallBonus`, `treasuryBonus`).
It will rot again next cycle and the report will say so, which is the mechanism working.
Rejected: dropping the key — load-safe (§2), but the throw at `cli.js:2561-2564` would then
name a key that no longer exists, and `--trials` would become the only manual override.

### 3.9 Ruling (g): forward compatibility is already in hand; nothing is built and nothing is foreclosed

Every seat is a real template, so `Role` names a build (`dps_water`, `tank`, …) on every one
of ~104 rows, not on 16. The seven-column contract can grow: `Code.gs` is width-agnostic
(`:104-111`), `combat.py` reads fixed indices `:86-92` and guards cells 0–6 only (`:236`), and
`combatTab.js:25-32` already says the three places a column is added. The "which build should
I run" feature is not built here.

## 4. The contracts, to the cell

### 4.1 The sheet tab — **unchanged**

`Member | Trial Hrid | Team | Role | Slot | Guild Id | Generated At`, one row per seated
member, `Guild Id` numeric, `Generated At` identical on every row, sorted Team then Slot
(`combatTab.js:88-89`; the sort is lexicographic so `dps_water 10` precedes `dps_water 2` —
cosmetic, the reader does not order on it). What changes is the **row count**: ~104 (SC) and
~96 (LI) instead of 32 and 29; `Role` takes any of the 13 template ids; `Slot` labels reach
`dps_water 14`. The endpoint clears `max(old last row, new rows)` (`Code.gs:180`), so a
shrink week leaves no orphans.

### 4.2 `trials.json["combat"]` — **unchanged**

`{available, unavailable, source, generated_at, trials: [{hrid, team, party_size, roster:
[{name, role, slot}]}]}`, `party_size == len(roster)` (`combat.py`, pinned at
`tests/test_combat.py:126`, `:473`). `party_size` becomes ~52 / ~48. No `characterId` in any
row (`combat.py:117-119`).

### 4.3 The Apps Script payload — **unchanged**

`{ secret, tab, header, rows }` (`combatTab.js:146`), ~105 rows × 7 cells. No cap on the
endpoint (`Code.gs:112`, `:152-156`).

### 4.4 `data/pins.json` — grows in provenance, not in schema

Schema v1 unchanged (`validatePins`, `pins.js:69-110`; extra keys on a slot are tolerated).
After the first weekly run: `source: "optimizer@2026-W36"`, `cycle: "2026-W36"`, a `_comment`
saying it is the optimiser's own recommendation (passed via `writePinsBack`'s existing
`comment` parameter, `:325-327`), and this guild's teams carrying ~52 slots each plus the aura
overlay. The previous file is archived as `data/pins.2026-W35.json` (`:340-347`). **This is a
tracked file and it will carry member display names**, which its own `_comment` already
sanctions for this repository ("distributed via a secret gist"). It is not to be committed by
this work (working-tree discipline).

### 4.5 `resolvePinsFor` — one optional parameter, backward compatible

`resolvePinsFor({ parsed, guild, index, cycle, trials, file, knownIds = null })`. Returns
the existing shape plus `carriedFromDisk: <int>`. With `knownIds` absent, behaviour and
return value are exactly today's (plus the zero).

### 4.6 The CLI surface

`report --publish-combat` and `--publish-combat=preview` imply `--optimize` (and therefore
`--simulate`). New flag `--no-optimize`: never search, whatever else is passed — the waiver.
`report --write-pins` unchanged in shape; it now passes a comment. Everything `optimize`
accepts is already forwarded to `report` (`cli.js:3090-3102`), so `--budget 90m` works.

**The weekly command**, for each guild:

```bash
node optimizer/cli.js report --guild sc --write-pins --publish-combat --budget 90m
node optimizer/cli.js report --guild li --write-pins --publish-combat --budget 90m
```

### 4.7 What does not change

`optimize/assign.js`, `optimize/candidate.js`, `optimize/composition.js`,
`optimize/search.js`, `optimize/styleSeed.js`, `model/templates.js`,
`sources/trialAssignments.js`, `sources/trialSignup.js`, `report/render.js`,
`optimizer/src/publish/combatTab.js`'s `HEADER`/`TAB_BY_GUILD`/`combatRowsFromAssignment`;
farm/guild's `apps-script/Code.gs`, `src/combat.py`, `src/config.py`, `src/build.py`,
`tests/*`; `scli-roster.user.js`. **farm/guild has no code change in this plan** — the plan
lives here because the acceptance test is its artefact.

## 5. Degraded paths

| situation | what happens | said where |
|---|---|---|
| Weekly command, all 13 templates transcribed, budget 90m | search runs; winner (or incumbent if tied) published; ~104 rows | `reportReport` prints seats / seatsWanted |
| A template is `status: "stub"` | search skipped; pins composition re-solved and published; week 1 that is 32 rows, week 2+ last week's ~104 | note "THE SEARCH DID NOT RUN — …"; WARNING when short |
| Budget too small for round 1 | round 0 fixes 52/52, DPS scales, tanks/healers stay at incumbent counts; confirm trimmed | the budget notes (`search.js:745-757`, skipped stages) |
| No candidate beats the incumbent | incumbent published (week 1: 32 rows; week 2+: last week's allocation) | note "the roster below is the INCUMBENT…"; WARNING when short |
| `--no-optimize` | exactly today's behaviour: pins composition, no search, no simulation unless `--simulate` | `NO SEARCH RAN` in the seats line |
| POST aborts at 90 s | throws; exit 1; message says UNKNOWN, names the tab and the stamp to look for | the CLI refusal |
| Tab not parsed, disk pins are the optimiser's | today's disk fallback (`pins.js:219-239`), unchanged | existing warning |
| Tab parsed, disk pins synthetic or hand-seeded | no merge (`optimizer@` guard) | `carriedFromDisk: 0`, no note |
| Member left the guild since last week | their carried pin is dropped (`knownIds`) | — |
| farm/guild reads ~104 rows | unchanged reader; `party_size` ~52 | — |

## 6. Files touched

### `/Users/morgan/pie/SCLIRoster/`
| file | change |
|---|---|
| `optimizer/src/publish/combatTab.js` | `:139` `timeoutMs = 90_000`; `:158-163` the abort branch split in two with the UNKNOWN message. ~20 lines. |
| `optimizer/test/combat-tab.test.js` | `:323-334` edit; +2 tests (§8). |
| `optimizer/src/optimize/pins.js` | `resolvePinsFor` `:210-240`: `knownIds`, `carriedFromDisk`; new private `carryOwnPins`. ~45 lines incl. doc. |
| `optimizer/test/pins.test.js` | `:294-317` edit; +5 tests (§8). |
| `optimizer/cli.js` | `doAssign` `:709-713` and `doOptimize` `:1104-1107`: pass `knownIds`; `doReport` `:1571-1590`: `wantSearch`, stub degrade, notes, `wantSim`; `:1843-1852`: `comment`; `:1866-1893`: `seats`/`seatsWanted`/`pool`/`searched` on `published`; `reportReport` `:2004-2022`: the seats line and WARNING; `main` `:3074-3095`: `noOptimize`; USAGE `:2800-2816`; doc comment `:1546-1564`. ~90 lines. |
| `optimizer/test/report-weekly.test.js` | **NEW.** 4 source-pin tests (§8). ~60 lines. |
| `data/guild.json` | `:171-174` four values. |
| `optimizer/README.md` | `:76-83` the weekly command; `:86-92` the write paragraph gains "the whole allocation to partyCap"; `:172-178` the stale "all twenty shipped templates are stubs" sentence corrected; a wall-clock line after step 15's measurement. ~15 lines. |
| `data/pins.json`, `data/pins.2026-W35.json` | **written by the first live run, not edited** (§4.4). |

### `/Users/morgan/pie/farm/guild/`
| file | change |
|---|---|
| — | No code. The build and tests are re-run as verification (steps 17–18). |

## 7. Steps — ordered, each with its verification

The order is load-bearing: the timeout fix (steps 1–2) must land before anything posts ~104
rows; the pins merge (3–5) before the CLI is wired to write pins; the CLI (6–9) before the
offline rehearsal (12); the live SC preview (14) before any live write; SC before LI so the
first live write is the one the acceptance test watches.

**Step 0 — checkpoints and rollback anchors.** ~5 min
`git -C /Users/morgan/pie/SCLIRoster rev-parse --short HEAD` → `fab85ab`;
`git -C /Users/morgan/pie/farm/guild rev-parse --short HEAD` → `086de16`. Because
`optimizer/cli.js` is dirty with today's uncommitted work and `combatTab.js` /
`combat-tab.test.js` are untracked, `git checkout` cannot restore them: copy the four files
this plan edits to the scratchpad first —
`mkdir -p $SCRATCH/pre-fills && cp optimizer/cli.js optimizer/src/publish/combatTab.js optimizer/test/combat-tab.test.js optimizer/src/optimize/pins.js $SCRATCH/pre-fills/`
(`pins.js` is clean at HEAD, copied for symmetry). Re-run `npm test` once → 987 / 986 pass /
1 pre-existing failure, as the comparison point.

### The write path survives 104 rows

**Step 1 — `optimizer/src/publish/combatTab.js`** ~20 min

- `:139`: `timeoutMs = 90_000 }) {` with a comment: 20 s fired on 29 rows on 2026-09-09
  after the write had landed; 90 s bounds the wait without claiming to know the outcome.
- `:158-163` becomes:
  ```js
  } catch (err) {
      if (err?.name === 'TimeoutError' || err?.name === 'AbortError') {
          // A client that stopped waiting has learnt NOTHING about the server.
          // On 2026-09-09 Apps Script finished a 29-row LI write after this
          // client gave up at 20 s, and the old message said "Nothing was
          // written" — which was false. So: UNKNOWN, and where to look.
          const stamp = (rows && rows[0] && rows[0][HEADER.indexOf('Generated At')]) || null;
          throw new Error(`${where} did not answer within ${timeoutMs / 1000}s. `
              + 'THE OUTCOME IS UNKNOWN: Apps Script may have completed after this '
              + `client stopped waiting. Open the "${tab}" tab and read its Generated At `
              + `column${stamp ? `: ${stamp} on every row means this run's `
                  + `${rows.length} row(s) landed` : ''}; an older stamp, or the previous `
              + 'row count, means they did not. Nothing was retried.');
      }
      throw new Error(`${where} could not be reached: ${err?.message || err}. `
          + 'Nothing was written.');
  }
  ```
  `HEADER`, `tab` and `rows` are all in scope (`:38`, `:137`).

Verify: `node --check optimizer/src/publish/combatTab.js`;
`node --test optimizer/test/combat-tab.test.js` → 1 fail (`:323`, the message changed), 12 pass.

**Step 2 — `optimizer/test/combat-tab.test.js`** ~20 min

- `:323-334`: rename to `a timeout is reported as UNKNOWN, naming the tab and the stamp —
  never as "nothing written"`; keep the `TimeoutError` fake; assert
  `/did not answer within 20s/`, `/OUTCOME IS UNKNOWN/`, `/"SC Combat Teams"/`,
  `/2026-09-09T12:00:00.000Z/` (the fixture's `GENERATED`, `:12`), and
  `assert.ok(!/Nothing was written/.test(err.message))`. The `leaky` half of the test
  (`:337-349`) is unchanged — `could not be reached` still ends `Nothing was written`.
- New `an AbortError by that name is the same unknown outcome`: `e.name = 'AbortError'`, same
  assertions.
- New `the default timeout is 90 s, and it is a parameter, not a constant`: read the module
  source (`fs.readFileSync`, as `:356-…` already does for the grep pin) and
  `assert.match(src, /timeoutMs = 90_000/)`.

Verify: `node --test optimizer/test/combat-tab.test.js` → 15 pass.

### The pins carry the whole roster

**Step 3 — `optimizer/src/optimize/pins.js`: `resolvePinsFor` merges the optimiser's own pins under the tab's** ~45 min

Replace `:210-217` (the tab branch) and add the helper after `:240`:

```js
export function resolvePinsFor(opts = {}) {
    const { parsed = null, guild, index, cycle, file = PINS_FILE, trials,
            knownIds = null } = opts;
    const warnings = [];

    if (parsed && parsed.ok !== false && parsed.teams) {
        const seeded = seedPins(parsed, { guild, index, cycle, trials,
            source: opts.source || `Trial Assignments@${new Date().toISOString()}` });
        const carried = knownIds
            ? carryOwnPins(seeded.pins, { guild, file, knownIds, warnings }) : 0;
        return { ...seeded, warnings: [...warnings, ...seeded.warnings],
                 fromDisk: false, file: null, carriedFromDisk: carried };
    }
    // …the disk-fallback branch, byte-for-byte as today, each return gaining
    // `carriedFromDisk: 0`…
}

/**
 * THE OFFICERS' PINS WIN; OURS FILL THE GAPS. (2026-09-09, D1's continuity.)
 *
 * Since the optimiser designs the whole composition to partyCap, ~72 of the
 * ~104 seated members hold no pin on the officers' tab and would be "newly
 * seated" every week — free to swap teams whenever a level moves. So when the
 * tab parses, the slots the optimiser itself wrote last week (`report
 * --write-pins`) are carried in for every member the tab does NOT name. Three
 * guards, each load-bearing:
 *   - the file must be the optimiser's own (`source` starts `optimizer@`) — a
 *     hand-seeded or fixture file is fallback-only, as before;
 *   - the member must be in THIS run's roster (`knownIds`) — the tracked
 *     data/pins.json is synthetic (ids 1000-1019) until the first real write,
 *     and a member who has left must not count as a seat in the incumbent;
 *   - the member must not be named anywhere on the tab — a pin is a bias the
 *     officers may override, so theirs is the only one kept.
 * Called only with `knownIds`; without it this function is not reached and
 * `resolvePinsFor` behaves exactly as it did before this date.
 */
function carryOwnPins(pins, { guild, file, knownIds, warnings }) {
    let disk = null;
    try { disk = loadPins({ file }); } catch (err) {
        warnings.push(`${file} is on disk but INVALID (${err.message}); no pins were `
            + 'carried from it.');
        return 0;
    }
    if (!disk || !String(disk.source || '').startsWith('optimizer@')) return 0;
    const onTab = new Set();
    for (const t of Object.values(pins.teams)) {
        for (const s of t.slots || []) {
            if (s.characterId !== null && s.characterId !== undefined) onTab.add(s.characterId);
        }
    }
    let carried = 0;
    for (const teamName of (guild && guild.tabs && guild.tabs.teams) || []) {
        const from = (disk.teams || {})[teamName];
        if (!from) continue;
        if (!pins.teams[teamName]) pins.teams[teamName] = { trialHrid: null, slots: [] };
        for (const s of from.slots || []) {
            if (s.characterId === null || s.characterId === undefined) continue;
            if (!knownIds.has(s.characterId) || onTab.has(s.characterId)) continue;
            pins.teams[teamName].slots.push({ ...s, carried: disk.source });
            carried++;
        }
    }
    if (carried) {
        warnings.push(`${carried} pin(s) for members the Trial Assignments tab does not `
            + `name were carried from ${file} (${disk.source}, cycle "${disk.cycle}"), so `
            + 'the whole roster has week-to-week continuity and the incumbent is last '
            + 'week\'s PUBLISHED allocation. Wherever the tab names a member, the tab\'s '
            + 'pin is the only one kept.');
    }
    return carried;
}
```

`loadPins` is `:112-115` in the same file. A carried slot keeps its `label`, `role`, `class`,
`aura`, `nameAsWritten`, `characterId`, `resolution` from `pinsFromAssignment` (`:264-306`),
which is what `compositionFromPins` (`candidate.js:203-247`), `pinIndex` (`pins.js:376-387`)
and `roleStability` (`assign.js:124-166`) read. `validatePins` tolerates the extra `carried`
key (it checks named fields only, `:87-101`).

Verify: `node --test optimizer/test/pins.test.js` → 14 pass (no test passes `knownIds`);
`node --test optimizer/test/pins-writeback.test.js optimizer/test/assign.test.js` → unchanged.

**Step 4 — `optimizer/test/pins.test.js`** ~40 min

Fixture: a temp pins file via `os.tmpdir()` (as `:161-166` does), body
`{ schemaVersion: 1, cycle: '2026-W35', source: 'optimizer@2026-W35', teams: { 'SC Team 1':
{ trialHrid: '/guild_combat/badger', slots: [ …] } }, unresolved: [] }`. Seed from
`trial-assignments.csv` as `:143-146` does; compute `onTab` from the seeded result; pick one
id that IS on the tab (e.g. `1000`, Alpha) and one that is in `INDEX` (`:44`) but not on the
tab, plus a foreign id `5555`. Tests:

| test | pins |
|---|---|
| `the optimiser's own pins are CARRIED for members the tab does not name` | `carriedFromDisk === 1`; the slot is present on `SC Team 1` with `carried: 'optimizer@2026-W35'`; the warning matches `/carried from .*optimizer@2026-W35/` and `/PUBLISHED allocation/` |
| `the officers' pin wins where both name a member` | a disk slot for `1000` as `healer_blooming` on `SC Team 2` is NOT added; `1000`'s pins are exactly the seeded ones |
| `a synthetic or hand-seeded file is never merged` | `file: PINS_FILE` (today's synthetic), `knownIds` containing `1000` → `carriedFromDisk === 0`, pins deep-equal the seeded pins |
| `a carried pin must belong to this run's roster` | disk slot for `5555` → dropped, `carriedFromDisk` unchanged |
| `without knownIds nothing changes` | same inputs, no `knownIds` → `carriedFromDisk === 0` and `pins` deep-equal |
| *(edit)* `:294-317` → `data/pins.json validates, and its provenance is honest` | `source` matches `/SYNTHETIC\|^optimizer@/`; if synthetic, `_comment` mentions `SEEDED FROM THE SYNTHETIC FIXTURE`; if `optimizer@`, `_comment` mentions `optimiser` and NOT `SYNTHETIC FIXTURE`. The aura-`positional` loop (`:305-316`) applies only in the synthetic case (the optimiser writes `resolution: 'exact'`, `pins.js:291`). |

Verify: `node --test optimizer/test/pins.test.js` → 19 pass.

**Step 5 — `optimizer/cli.js`: both call sites pass `knownIds`** ~10 min

- `doAssign` `:709-713` and `doOptimize` `:1104-1107`: add
  `knownIds: new Set(m.merged.members.filter((x) => x.guildId === guild.guildId).map((x) => x.characterId)),`
  — in-guild members regardless of availability, so an unavailable member keeps their pin for
  the week they return. (`m.merged.members` is the folded roster; `allMembers` at
  `merge.js:187` includes roll-call-only records and is what the *name* index is built from.)

Verify: `node --check optimizer/cli.js`; `node optimizer/cli.js assign --guild sc --offline`
runs and prints the same seats as before (the fixture file is synthetic → nothing carried).

### The weekly command becomes the search

**Step 6 — `optimizer/cli.js` `doReport` `:1571-1590`: the implication, the stub degrade, the notes** ~35 min

Replace `:1573-1590` (`let search = null; … const wantSim = …`) with:

```js
    // --- D1 (2026-09-09): A PUBLISH IS A SEARCH --------------------------------
    // `--publish-combat` implies `--optimize` exactly as `--optimize` implies
    // `--simulate` below. The sheet tells every member where to be; a roster
    // that was never searched is the officers' 16-seat core re-solved (32 rows
    // on 2026-09-09, 77 benched), which is what D1 rejected. `--no-optimize`
    // is the waiver and the rollback: with it this function is its pre-D1 self.
    const wantSearch = !opts.noOptimize
        && (Boolean(opts.optimize) || Boolean(opts.publishCombat));

    let search = null;
    let assignResult = a;
    let candidate = a.candidate;
    if (wantSearch) {
        // The stub gate, HERE as well as inside doOptimize, so a stub DEGRADES
        // the weekly run instead of stopping it (ruling c). Same check, same
        // message; only what happens next differs. Any other error propagates.
        let stubbed = null;
        try {
            assertSearchable(a.templates,
                [...new Set(ROLES.map((r) => pickTemplate(a.templates, r).id))].sort());
        } catch (err) {
            if (!/status "stub"/.test(err.message)) throw err;
            stubbed = err.message;
        }
        if (stubbed) {
            notes.push(`THE SEARCH DID NOT RUN — ${stubbed} The roster below is the `
                + 'composition derived from the PINS (last week\'s published allocation '
                + 'once one exists; the officers\' named core before that), re-solved on '
                + 'this week\'s pool. This is a DEGRADED week: transcribe the template and '
                + 're-run.');
        } else {
            search = await doOptimize({ ...opts, quiet: opts.quiet });
            const pick = search.improved && search.winner ? search.winner : search.incumbent;
            assignResult = pick.assignResult;
            candidate = pick.candidate;
            notes.push(...search.notes.filter((n) => !notes.includes(n)));
            notes.push(search.improved
                ? 'the roster below is the SEARCH WINNER, which beat the incumbent under '
                  + 'identical seeds (C4). Week 1 the incumbent is the officers\' named '
                  + 'core alone (a floor); from week 2 it is last week\'s published '
                  + 'allocation.'
                : 'the roster below is the INCUMBENT, re-solved: no candidate beat it '
                  + 'under identical seeds, so it is what is published (§II.2).');
        }
    }

    // --- the simulation, if one was asked for -----------------------------
    const wantSim = Boolean(opts.simulate) || search !== null;
```

`assertSearchable`, `ROLES`, `pickTemplate` are imported at `:56`. Note for the implementer:
`a.templates` is `loadTemplates()` from the default directory (`doAssign`, `:703`); the
`--templates DIR` dev flag is honoured only inside `doOptimize` (`:1068-1069`), so a stub in
the default set with a transcribed alternative under `--templates` would degrade rather than
search — say so in a one-line comment; it is a developer path, not the weekly one.

Also update the doc comment `:1546-1564` (THREE MODES): add under `--optimize` "Implied by
`--publish-combat`; `--no-optimize` waives it."

Verify: `node --check optimizer/cli.js`.

**Step 7 — `optimizer/cli.js` `doReport` `:1843-1852` and `:1866-1893`: the pins comment and the seat count** ~20 min

- In the `writePinsBack({...})` call (`:1843-1852`) add
  ```js
  comment: [
      `THE OPTIMISER'S OWN RECOMMENDATION for ${a.cycle.id}, written by \`report --write-pins\` at ${model.generatedAt}.`,
      'Next week these are the PINS: a bias (sigma_team / sigma_bench) toward last week\'s seat, never a constraint,',
      'merged UNDER the officers\' Trial Assignments tab — wherever the tab names a member, the tab wins (pins.js carryOwnPins).',
      'Names appear here because §2.3 stores nameAsWritten; this repository is distributed via a secret gist. Do not make it public.',
  ],
  ```
  (`writePinsBack` writes `_comment` when given, `pins.js:363`.)
- In the publish block, after `const block = …` (`:1868-1869`):
  ```js
  const pool = a.eligible.length;
  const seatsWanted = Math.min(pool,
      ((guild.tabs && guild.tabs.teams) || []).length * (guild.partyCap ?? 48));
  ```
  and add `seats: block.rows.length, seatsWanted, pool, searched: search !== null` to both
  `published = {…}` objects (`:1880-1881`, `:1888-1889`). `guild.partyCap` is the
  `data/guild.json` value (`fitToPool` reads the same field, `candidate.js:264`).

Verify: `node --check optimizer/cli.js`.

**Step 8 — `optimizer/cli.js` `reportReport` `:2004-2022`: say the seat count out loud** ~15 min

After the `combat  <tab>  N row(s) written` / preview lines and before the `unnamed` block:

```js
        const p = out.published;
        say(`  ${p.seats} seat(s) published of ${p.seatsWanted} wanted `
            + `(min(pool ${p.pool}, teams x partyCap))${p.searched ? '' : '   NO SEARCH RAN'}`);
        if (p.seats < p.seatsWanted) {
            say('  WARNING: the published allocation is SHORT of the pool-capped seat count.');
            say(p.searched
                ? '  The search could not fill it — read the notes: budget, infeasible seats, '
                  + 'or a tie with a smaller incumbent (week 1: the officers\' core).'
                : '  Nothing was searched (a stub template, or --no-optimize). Members with '
                  + 'no row have no assignment this week.');
        }
```

Verify: `node --check optimizer/cli.js`.

**Step 9 — `optimizer/cli.js` `main` `:3074-3095` and USAGE `:2800-2816`** ~10 min

- Beside `optimize: Boolean(flags.optimize),` (`:3076`): `noOptimize: flags['no-optimize'] === true,`.
- USAGE `--publish-combat` (`:2800-2810`): append "Implies --optimize (a publish is a
  search); the whole allocation to partyCap is what is written, ~104 rows for SC."
- New line after `--optimize` (`:2813-2816`):
  `  --no-optimize      never search, even with --publish-combat: the pins composition, re-solved. The rollback.`

Verify: `node optimizer/cli.js --help 2>&1 | grep -c "no-optimize"` → ≥ 1 (or however USAGE
prints; `node optimizer/cli.js` with no command prints it, `:2882+`).

**Step 10 — `optimizer/test/report-weekly.test.js` (new)** ~30 min

Four source-pin tests in the manner of `search.test.js:402-417` (read `cli.js`, slice from
`export async function doReport` to `function reportReport`):

| test | asserts |
|---|---|
| `--publish-combat implies the search, and --no-optimize is the waiver` | `/const wantSearch = !opts\.noOptimize\s*&&\s*\(Boolean\(opts\.optimize\) \|\| Boolean\(opts\.publishCombat\)\)/` in the `doReport` slice; `/noOptimize: flags\['no-optimize'\] === true/` in the `main` slice |
| `a stub template degrades the weekly report instead of stopping it` | `/assertSearchable\(a\.templates/` and `/if \(!\/status "stub"\/\.test\(err\.message\)\) throw err;/` in `doReport`; and `/THE SEARCH DID NOT RUN/` |
| `a short publish is said out loud, and names whether a search ran` | `/seatsWanted/` in `doReport`'s publish block; `/p\.seats < p\.seatsWanted/` and `/NO SEARCH RAN/` in `reportReport` |
| `the weekly command passes knownIds at both call sites` | two matches of `/knownIds: new Set\(m\.merged\.members/` in `cli.js` |

Verify: `node --test optimizer/test/report-weekly.test.js` → 4 pass; then the whole suite
`npm test` → 987 + 11 = 998 tests, 997 pass, the same 1 pre-existing failure.

### Data and documentation

**Step 11 — `data/guild.json` `:171-174`** ~2 min
`"SC Team 1": "/guild_combat/badger"`, `"SC Team 2": "/guild_combat/swarm"`,
`"LI Team 1": "/guild_combat/badger"`, `"LI Team 2": "/guild_combat/swarm"`.
Verify: `node -e 'JSON.parse(require("fs").readFileSync("data/guild.json"))'` parses;
`node optimizer/cli.js assign --guild sc --offline 2>&1 | grep -c DISAGREES` → 0 (the
offline signup fixture names the same pair — if it does not, the note is the fixture's, and
the live check in step 14 is the one that counts).

**Step 12 — offline rehearsal of the whole path** ~5 min + run time
```bash
cd /Users/morgan/pie/SCLIRoster && time node optimizer/cli.js report --guild sc --offline \
  --publish-combat=preview --budget 3m --out $SCRATCH/offline
```
Expect: the search runs on the 22-member fixture (one team at 22, `splitLadder`'s
`total < 2 x partyMin` branch, `composition.js:409-420`), the preview is written, the seats
line prints. Then
```bash
node -e '
const c=JSON.parse(require("fs").readFileSync(process.argv[1]));
const ids=new Set(require("fs").readdirSync("data/templates").filter(f=>f.endsWith(".json")).map(f=>f.slice(0,-5)));
const bad=c.rows.filter(r=>!ids.has(r[3])); console.log("rows",c.rows.length,"untemplated roles",bad.length, "unnamed",c.unnamed.length);
process.exit(bad.length?1:0)' $SCRATCH/offline/combat-sc-2026-W36.json
```
→ `untemplated roles 0`. If the offline engine path refuses for a fixture-specific reason,
run the same with `--no-optimize` to prove the waiver, and carry the search rehearsal into
step 14.

**Step 13 — `optimizer/README.md`** ~15 min
- `:76-83`: replace the `report --publish-combat` example with the weekly command (§4.6) and
  a line for `--no-optimize`.
- `:86-92`: "one row per seated member" → "one row per seated member — **the whole
  allocation to `partyCap`**, ~104 rows for SC, because `--publish-combat` implies
  `--optimize`".
- `:172-178`: the sentence "since all twenty shipped templates are stubs that refusal is the
  normal path today" is false since 2026-09-04 — correct it to "all 13 are transcribed; a
  stub degrades `report` to the pins composition and says so".
- Leave a placeholder line for the measured wall clock, filled at step 15.

Verify: `grep -n "no-optimize\|whole allocation" optimizer/README.md` → both present.

### Live — SC first, preview before write

**Step 14 — live SC preview, no pins write, timed** ~5 min + up to 90 min unattended
```bash
cd /Users/morgan/pie/SCLIRoster && time node optimizer/cli.js report --guild sc \
  --publish-combat=preview --budget 90m 2>&1 | tee $SCRATCH/sc-preview.log
```
No `--write-pins` here: writing pins between the preview and the live run would change the
live run's incumbent (§3.4). Expect in the log: `Trial Signup's header names Swarm + Badger`;
no `DISAGREES` line (step 11); the search's round lines; `incumbent … proposal …
IMPROVEMENT FOUND`; `N seat(s) published of 104 wanted`. Then:
```bash
node -e '
const c=JSON.parse(require("fs").readFileSync("data/exports/combat-sc-2026-W36.json"));
const by={}; for (const r of c.rows) by[r[2]]=(by[r[2]]||0)+1;
console.log("rows",c.rows.length,"per team",by,"unnamed",c.unnamed.length);
console.log("holychikenz:", c.rows.filter(r=>r[0].toLowerCase()==="holychikenz").map(r=>`${r[2]} ${r[3]} ${r[4]} ${r[1]}`));'
```
→ rows ≈ 104, per team ≈ 52/52, `holychikenz` one row with a `Role` in the 13 template ids.
Record the `time` figure and the `wall clock … s of a 5400 s budget` line
(`reportOptimize`'s print does not run under `report`; read `verdict.budget.elapsedMs` from
`data/exports/report-sc-2026-W36.json` instead).

**If `holychikenz` is absent:** he is one of `benched` or `infeasible` in the report JSON
(`--include-names` to see names; otherwise match `m<characterId>` against the roster cache).
`infeasible` means `measuredWeaponless` for every DPS seat (`assign.js:273-276`) — check
`gearSeen` in `data/cache/sc-roster.json`; `benched` means the five weakest by fitness, which
the ResearchPack's 688K-damage Badger record makes unlikely. Either is the allocation being
correct and the acceptance test needing a different character; neither is a defect in this
plan.

**Step 15 — record the wall clock** ~5 min
From step 14: `verdict.budget.elapsedMs`, which rounds ran (`verdict.rounds[].skipped`), and
`msPerPlayerIteration`. Write the figure into `optimizer/README.md`'s placeholder (step 13)
and into §12 of this plan. If round 1 was skipped at 90 min, say so there: D1's tank/healer
scaling then waits for a larger budget or a cheaper round 1, and that is a follow-up.

**Step 16 — live SC publish, with pins** ~5 min + run time (mostly cache)
```bash
node optimizer/cli.js report --guild sc --write-pins --publish-combat --budget 90m 2>&1 \
  | tee $SCRATCH/sc-publish.log
```
The search is a cache hit throughout (same config, same seeds — README `:126-129`), so this
is minutes. Expect `combat  SC Combat Teams  N row(s) written`, `N seat(s) published of 104
wanted`, no WARNING, and the pins lines (`wrote data/pins.json … previous cycle "2026-W35"
preserved as data/pins.2026-W35.json`). Then the sheet itself:
```bash
curl -sL 'https://docs.google.com/spreadsheets/d/1b5_zID6K4WRaFXnBMJijSEXr_4l2gi40eFKxuvRJQAE/gviz/tq?tqx=out:csv&sheet=SC%20Combat%20Teams' > $SCRATCH/sc-tab.csv
tail -n +2 $SCRATCH/sc-tab.csv | wc -l        # ≈ 104
grep -ci holychikenz $SCRATCH/sc-tab.csv      # 1
head -1 $SCRATCH/sc-tab.csv                   # the seven headers, verbatim
```
And the pins file: `node -e 'const p=JSON.parse(require("fs").readFileSync("data/pins.json")); console.log(p.source, p.cycle, Object.fromEntries(Object.entries(p.teams).map(([t,v])=>[t,v.slots.length])))'`
→ `optimizer@2026-W36 2026-W36 { 'SC Team 1': ~57, 'SC Team 2': ~57, 'LI Team 1': 21, 'LI Team 2': 21 }`
(SC ~52 seats + 5 aura slots; LI still synthetic until step 17). `git status --short
data/pins.json` → ` M` — expected, not to be staged.

**If the POST aborts:** the message now says UNKNOWN and names the tab; run the `curl` above
and read `Generated At` against the report's `generatedAt`. If it landed, nothing to do; if
not, re-run step 16 (the endpoint rewrites from A1).

**Step 17 — live LI** ~5 min + run time
Steps 14 and 16 with `--guild li`, `holychik3nz`, `LI%20Combat%20Teams`, `96 wanted`.

### farm/guild reads it

**Step 18 — the build** ~10 min
```bash
cd /Users/morgan/pie/farm/guild && uv run --no-dev python -m src.build
python3 -c "
import json
for f, who in (('_site/trials.json','holychikenz'), ('_site/li/trials.json','holychik3nz')):
    c = json.load(open(f))['combat']
    print(f, c['available'], c['unavailable'] or '-', [(t['team'], t['party_size']) for t in c['trials']])
    assert c['available'], c['unavailable']
    assert any(r['name'].lower() == who for t in c['trials'] for r in t['roster']), who
    assert all(t['party_size'] == len(t['roster']) for t in c['trials'])
print('ok')"
```
→ `available True`, party sizes ≈ 52/52 and ≈ 48/48, both characters found. The summary line
in the build output names `combat` with the row counts.

**Step 19 — the suites** ~10 min
`uv run --extra dev python -m pytest tests/ -q` → 479 passed (nothing changed here);
`cd /Users/morgan/pie/SCLIRoster && npm test` → 998 tests, 997 pass, 1 pre-existing failure.

**Step 20 — in game, on `holychikenz`** ~15 min
Open Guild ▸ Trials: two gold tiles (Enhancing — the skilling assignment the ResearchPack
records; Trial Badger — this allocation), both panel verdicts `agree`. Then change the
in-game combat sign-up to Swarm: the amber dashed ring appears on Trial Swarm, the gold glow
stays on Trial Badger, the panel names both. Change it back. This exercises the mismatch
path that D1 makes load-bearing.

**Total estimated time:** ~4 h at the keyboard (steps 0–13, 15, 18–20) plus 2 × up to 90 min
unattended (steps 14, 17) — the second SC run and both LI runs are cache-warm and short.

## 8. Test plan

### `optimizer/test/combat-tab.test.js` (13 → 15)
| test | pins |
|---|---|
| *(edit)* `a timeout is reported as UNKNOWN, naming the tab and the stamp — never as "nothing written"` | `/OUTCOME IS UNKNOWN/`, `/"SC Combat Teams"/`, the fixture stamp, and the absence of `Nothing was written`; the `leaky` half unchanged |
| `an AbortError by that name is the same unknown outcome` | `e.name = 'AbortError'` → same assertions |
| `the default timeout is 90 s, and it is a parameter, not a constant` | source match `/timeoutMs = 90_000/` |

### `optimizer/test/pins.test.js` (14 → 19)
The five new tests and the one edit of step 4. The existing disk-fallback tests
(`:143-175`) pass unchanged because they never pass `knownIds`.

### `optimizer/test/report-weekly.test.js` (new, 4)
Step 10's four source pins. Chosen over an end-to-end `doReport` unit test because `doReport`
has no simulator injection point (`doOptimize` calls `search()` with the real engine,
`cli.js:1202`), and `search.test.js:402-417` is the house precedent for pinning a CLI rule in
source. The end-to-end proof is step 12 (offline) and steps 14–17 (live).

### Existing tests that must change
`combat-tab.test.js:323-334` (message), `pins.test.js:294-317` (provenance). No other test
asserts a seat count, a bench size, or the `--publish-combat` semantics: `render.test.js`
`:387-436` test the headline against `pool` vs `seatsWanted` with synthetic candidates;
`search.test.js:378-440` drive `search()` directly; `assign.test.js:224` ("every slot … is
filled, and the surplus benches") is about the solver, which is untouched.

### farm/guild
No test changes. `tests/test_combat.py` (15) and the full suite (479) are re-run as
regression only.

## 9. Risks

**R1 — the roster churns week to week.** *Probability high without mitigation (72 unpinned
members, two teams with identical role sets, Hungarian ties broken by row order), impact
medium (members re-learn their team weekly; the mismatch warning fires for everyone who did
not check).* Mitigations: the pins merge (§3.4) gives every seated member a `sigma_team` and
`sigma_bench` bias toward last week from week 2; a fixed `--budget 90m` and the persisted
rate stabilise which rounds run; the tie-break prefers fewer moves (`search.test.js:278`);
seeds are fixed (`seedBase` 1). *Detection:* `movedCount` and "What changed from last week"
in the report, now over ~104 pinned. *Contingency:* raise `stability.team` in
`data/fitness.json` (the four sigmas are configuration, `assign.js:118-121`).

**R2 — the search picks a composition worse than the officers'.** *Probability low in
expectation (09-07d beat the core by +10.33 tiers; more bodies is more damage), medium in the
tails (the model's own MAE is 1.57 tiers, README `:643`; 38% of gear slots are assumed,
`report-sc-2026-W36.md:12`).* Mitigations: the verdict is paired under identical seeds
(`search.js:775-778`) and a tie ships the incumbent; the officers' pins survive as biases, so
their placements are the default wherever fitness is close; the report prints every seat's
reason and runner-up (`render.test.js:134-152`). *Detection:* the actuals replay
(`report/replay.js`, `data/actuals/sc-2026-W36.txt`) after the trial; a lower cleared tier
than the previous cycle at the same headcount. *Contingency:* `--no-optimize` republishes the
pins composition in minutes; an officer overrides a seat by editing `Trial Assignments`,
which the merge honours.

**R3 — the simulation pass makes the weekly run unacceptably slow.** *Probability medium
(13.3 min measured with round 1 skipped; round 1 estimated 15–70 min), impact low (the run is
unattended).* Mitigations: `--budget` is enforced, estimated from measured cost and skips or
trims what does not fit (`budget.js`); the second run of a week is cache-warm; step 15
records the real figure so the budget is set by measurement. *Detection:* the `wall clock …
of a … budget` line and `verdict.budget`. *Contingency:* `--budget 30m` accepts round-0
compositions (DPS scales, tanks/healers hold); `--resolution 0.10` for a coarse pass.

**R4 — a stub template blocks a Tuesday.** *Probability low (13/13 transcribed; a stub
appears only by hand), impact high if refused.* Mitigation: ruling (c) — the weekly run
degrades to the pins composition, publishes it, prints the WARNING and names the template.
*Detection:* `THE SEARCH DID NOT RUN` in the notes and `NO SEARCH RAN` on the seats line.
*Contingency:* transcribe and re-run; the cache makes the re-run cheap.

**R5 — the ~104-row POST times out.** *Probability medium at 20 s (it fired on 29 rows),
low at 90 s.* Mitigations: the raised default; the UNKNOWN message naming the tab and the
stamp so the operator checks rather than re-fires blind; the endpoint's clear-and-rewrite
makes a deliberate re-run safe (`Code.gs:189-190`). *Detection:* the CLI refusal text.
*Contingency:* the `curl` in step 16; re-run if the stamp is old.

**R6 — a member is silently absent under D3.** *Probability certain for ~5 members per
guild per week (109 eligible, 104 seats) and for anyone `infeasible`, impact low-medium (they
read "no combat assignment" and cannot tell it from a stale artefact).* Mitigations: the
report's `benched` and `infeasible` lists name them (by hrid; `--include-names` for names);
the CLI prints seats vs `seatsWanted`; the userscript already distinguishes "no combat data"
from "not assigned". *Detection:* a member asking. *Contingency and follow-up:* an eighth
column or a `bench` block on the sheet — the contract is growable (§3.9), and this is the
gap the user accepted and asked to have stated.

**R7 — week 1 publishes 32 rows anyway.** *Probability low (any round-0 candidate beats the
32-seat floor), impact medium.* Path: budget too small for even round 0, or `winner` null →
`pick = search.incumbent` → the officers' core is published. Mitigations: `--budget 90m`;
the WARNING on a short publish. *Contingency:* re-run with a larger budget.

**R8 — `data/pins.json` now carries ~104 real names in a tracked file.** *Probability
certain, impact low-medium (a private repo distributed via a secret gist; the file's own
`_comment` sanctions names and `assign --write-pins` has always written them).* Mitigation:
the new `_comment` says so and says "do not make it public"; the plan does not commit it;
`data/pins.2026-W35.json` (untracked) can be deleted after the first week. *Detection:*
`git status`.

**R9 — the pins merge inflates the incumbent with phantom seats.** *Probability medium
without guards (synthetic ids; departed members), low with them.* Mitigations: `knownIds`
(this run's roster) and the `optimizer@` prefix; a test for each. *Detection:*
`carriedFromDisk` against the roster size; the incumbent's `partySize` in the report.

**R10 — `holychikenz` is not seated.** *Probability low (688K Badger damage on the actuals
board; 104 of 109 seated), impact on the acceptance test only.* Mitigation: step 14's
contingency names where to look. This is the allocation working, not failing.

**R11 — the dirty trees.** *Probability certain, impact low.* `optimizer/cli.js` carries
today's uncommitted combat-glow edits; this plan edits it again. Step 0's copies are the
rollback anchor; nothing is staged or committed; SCLIRoster's one failing test stays failing
for its own reason.

**R12 — the wall-clock estimate is wrong.** *Probability medium (one measured run, a
prior-weighted rate, no rate file now).* Mitigation: step 15 replaces the estimate with a
measurement before the README claims a number; the budget enforces the ceiling regardless.

**If implementation gets stuck:** steps 1–2 ship alone (a better timeout on today's 32
rows); steps 3–5 ship alone (pins continuity with no behaviour change until a real pins file
exists); steps 6–10 ship alone (the implication, testable offline); the live steps can stop
after the SC preview with nothing written.

## 10. Rollback — per change, and what the flag restores

**The flag:** `--no-optimize` on the weekly command restores today's behaviour exactly —
the pins composition, no search, no simulation unless `--simulate`, and a publish of whatever
that yields (32 rows in week 1; from week 2, the merged pins make it last week's ~104). It is
the operator's 30-second rollback for a bad search without touching code. farm/guild's
`config.COMBAT_SOURCE_ENABLED = False` (`build.py:4563`, `:5082`) remains the downstream kill
switch: no `combat` key, the userscript glows skilling only.

**Code:** `optimizer/src/optimize/pins.js`, `data/guild.json` — clean at HEAD, so
`git -C /Users/morgan/pie/SCLIRoster checkout -- optimizer/src/optimize/pins.js data/guild.json`.
`optimizer/cli.js`, `optimizer/src/publish/combatTab.js`, `optimizer/test/combat-tab.test.js`
— dirty or untracked before this plan, so restore from step 0's copies:
`cp $SCRATCH/pre-fills/{cli.js,combatTab.js,combat-tab.test.js} …` to their paths. Delete
`optimizer/test/report-weekly.test.js`. `git checkout -- optimizer/test/pins.test.js`.
Verify: `npm test` → 987 / 986 / 1, as at step 0.

**Data:** `git checkout -- data/pins.json` restores the synthetic file; `rm data/pins.2026-W35.json`
(and any later archive). `pins.test.js:294` then passes in its original form.

**The sheet:** either leave it — farm/guild's cross-check marks it `available: false` the
moment the boss pair moves, and until then a 104-row allocation is a valid statement — or
republish the 32-row core with `report --guild sc --publish-combat --no-optimize` (after the
data rollback, so the pins are the officers' alone).

**Order:** flag first (instant), then sheet if wanted, then code and data; each step above is
independently verifiable by the command beside it.

**Triggers:** a published seat count below `seatsWanted` on two consecutive weeks without a
stub or budget note explaining it; an actuals replay materially below the previous cycle at
the same headcount; the UNKNOWN abort on every run (the endpoint has slowed — raise the
timeout further or investigate the deployment); any red in either suite beyond the one
pre-existing failure.

## 11. Success criteria

- `report --guild sc --write-pins --publish-combat --budget 90m` writes ~104 rows to
  `SC Combat Teams` and the LI command ~96 to `LI Combat Teams`, each row's `Role` one of the
  13 template ids, no `characterId` anywhere, header verbatim.
- `holychikenz` is on the SC tab and `holychik3nz` on the LI tab, each with a templated
  `Role`; `_site/trials.json` and `_site/li/trials.json` carry them with `available: true`
  and `party_size ≈ 52 / 48`; in game, two gold tiles and the mismatch ring on demand.
- The CLI prints `N seat(s) published of 104 wanted` with no WARNING; a forced stub (rename a
  template's status in a scratch copy under `--templates`, or edit and revert) prints
  `THE SEARCH DID NOT RUN` and still publishes.
- On abort the message contains `OUTCOME IS UNKNOWN` and the tab name and never `Nothing was
  written`; the default timeout is 90 s.
- `data/pins.json` reads `source: optimizer@2026-W36` with the new comment; the next
  `report` run's notes say pins were carried and its incumbent is ~52 + 52.
- `data/guild.json` no longer produces a `DISAGREES` note this cycle; `resolveTeamTrials`,
  `orderBySplit`, `disagreements` unchanged.
- The measured wall clock of the weekly run is written into `optimizer/README.md` and §12
  below, with which rounds ran.
- `npm test` → 998 tests, 997 pass, the one pre-existing failure; farm/guild pytest → 479.
- `assign.js`, `candidate.js`, `composition.js`, `search.js`, `render.js`, `Code.gs`,
  `combat.py`, `config.py`, `build.py`, the userscript: unchanged.
- Nothing staged, nothing committed, in either tree.

Quality checklist: APIs match the source cited (every function named exists at the line
given; the two new ones, `carryOwnPins` and the `report-weekly` tests, are defined here) ·
no contract changed · one flag, one rollback line · pins names stay inside the repository's
existing sanction · the three rejected alternatives per decision are named · the accepted
D3 gap is stated, not hidden.

## 12. Metadata

- Created 2026-09-09 against farm/guild `086de16` and SCLIRoster `fab85ab`, both dirty as
  described; anchors are working-tree line numbers.
- Agent: implementation-planner. DeepWiki: not applicable (no external library; Node for
  `AbortSignal.timeout`, Python per `.venv`/`uv`).
- Complexity: medium — one behavioural change in the pins layer, one flag implication, one
  message; the search itself is untouched. Risk: medium — the weekly output changes in kind
  (16 → 52 seats per team) and the wall clock is measured once; both are fenced by a
  one-flag rollback and an enforced budget.
- Wall clock of the weekly run: **to be filled at step 15** (prior measurement: 13.3 min at
  104 seats with round 1 skipped, 2026-09-07).
