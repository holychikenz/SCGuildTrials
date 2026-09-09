# Implementation plan — the combat-trial glow, and the sign-up/assignment mismatch

**ResearchPack:** the session brief (532 lines, every claim cited `file:line` against the
two live working trees, every WS/DOM/sheet shape measured). No external library is
involved, so there is no version to pin — the research is the codebase and this plan
re-verified every line it intends to edit. **Anchors:** `farm/guild` at `086de16` (dirty:
`src/build.py`, `src/config.py`, `src/trials.py`, `tests/test_trials.py`, `README.md`,
`research/*`, plus untracked `src/buildings.py`, `tests/test_build.py`,
`tests/test_buildings.py`, `tests/test_register_week.py` and two plans — the buildings and
weekly-assignments work, not yet committed); `SCLIRoster` at `fab85ab` (dirty: `README.md`,
`apps-script/Code.gs`, `apps-script/README.md`, `data/templates/dps_water.json`,
`plan-implementation.md`, `plan.md`, `research/armory/icon-map.json`). Line numbers below
are the working trees' as of 2026-09-09. **Baselines (re-measured today):** farm/guild
`.venv/bin/python -m pytest tests/ -q` → 461 passed in 7m34s; SCLIRoster `npm test` → 958
tests, 957 pass, 1 pre-existing unrelated failure (§2, row 12). **Precedent:**
`.claude/plans/weekly-assignments-on-register-implementation-plan.md` for the shape;
`086de16` for the Apps Script step; `src/buildings.py` for the reader.

---

## 1. What changes, in one paragraph

Today the userscript `/Users/morgan/pie/SCLIRoster/scli-roster.user.js` fetches one
artefact per guild — `trials.json` — finds the member's name in a skilling party and glows
that tile in Guild ▸ Trials; its own header says the two combat tiles "are never touched"
(`:106-110`). After this change the optimiser in `/Users/morgan/pie/SCLIRoster/optimizer`
gains its first and only spreadsheet write path — `report --publish-combat` POSTs the
recommended combat teams, one row per seated member, through the **existing** farm/guild
Apps Script endpoint to a **machine-owned** per-guild tab (`SC Combat Teams` /
`LI Combat Teams`) on the public sheet; farm/guild's build reads that tab against a fixed
seven-column contract, cross-checks its two bosses against the last two header cells of the
guild's own sign-up tab, and attaches a `combat` key to `trials.json`, degrading loudly to
`available: false` on any failure and never failing the deploy; the userscript then glows
**both** assigned tiles from the one artefact it already fetches, reads the member's own
sign-up off the WebSocket, and says plainly when sign-up and assignment disagree in either
discipline — distinguishing "no mismatch" from "sign-up not yet known" and from "your
sign-up is for a previous week". `config.COMBAT_SOURCE_ENABLED = False` removes the key
byte-for-byte; every other layer tolerates that.

## 2. The facts the plan rests on (all verified), and where the brief was wrong

| Claim in the brief | What the source actually says |
|---|---|
| The tile selector already matches the combat tiles; only `state.assignment.slug` fails them | Confirmed. `TILE_SEL = '[class*="GuildPanel_trialTile"]'` (`scli-roster.user.js:2058`); `decorate()` (`:2078-2100`) computes one `want` slug and toggles `scli-assigned` per tile. The six measured tiles all carry `GuildPanel_trialTile__HGaTA`. **No new selector.** |
| `normSkill` strips non-letters, so `trial_chameleon` → `trialchameleon` | Confirmed at `:308-310`; `slugOfTile` (`:2063-2076`) runs the sprite fragment AND the label fallback through it, so both paths converge on `trial<boss>`. The comment at `:305-306` already names "Trial Chameleon" → "trialchameleon". |
| The sprite FILENAME is not stable across bosses | Confirmed by the capture: Chameleon on `combat_monsters_sprite.ddb69185.svg`, Swarm on `misc_sprite.d7e5730f.svg`. Nothing may key on the file; the fragment is the key. n=2 — the live check in step 24 is mandatory. |
| `init_character_data` does not carry the sign-up fields | Confirmed by measurement on `wslog-20260909.jsonl`: the `guild` object's keys are `applicationsAutoAccept … currentTrialsData, currentWeekStartAt, … trialMinLevelsData, trialScheduleHourOffset, updatedAt` — no `signedUp*`. Those ride only on `guild_characters_updated` (per-member record keys include `characterID`, `signedUpCombatTrialHrid`, `signedUpSkillingTrialHrid`, `signupWeekStartAt`) and `guild_trial_signup_updated` (flat, `characterId`). **Both spellings are real** — `characterID` in the map record, `characterId` in the flat event. |
| The game's current week is available to the script | **Yes, and the brief under-sold it:** `guild.currentWeekStartAt` (`"2026-09-04T00:00:00Z"`) is on BOTH `init_character_data` and `guild_updated`, which `ingest()` already receives (`:3291-3292`). A sign-up is current iff `signupWeekStartAt === guild.currentWeekStartAt` — a game-string-to-game-string comparison, the same convention on both sides. The sibling writer had to infer "current week" as the max across the roster (`mwi-guild-signup-sync.user.js:450-451`); this script need not. |
| `guildWeeklyTrialSet.combatHrids` is exactly two hrids | Confirmed on both frame types: `["/guild_combat/swarm","/guild_combat/badger"]` today. `ingest()` reads only `skillHrids` (`:694-702`); the combat set is one more line. |
| `_write_guild` attaches provenance to `week` before writing `trials.json` | Confirmed: provenance `build.py:4886-4896`, register projection `:4902-4919` under `REGISTER_CARRIES_WEEK`, `data.json` `:4922-4927`, `trials.json` `:4930-4932`. `week` is `WeekResult.to_dict()` from `span[0]["week"]` (`:5173`). Attaching a key here leaves `src/trials.py` untouched and the golden test green (`tests/test_roster.py:363-481` calls `trials.run_week` at `:383` and never `_write_guild`). |
| `tests/test_register_week.py:250` fails the moment a key is attached | Confirmed: `assert set(published) == keys_before | {"provenance"}` for both guilds (loop `:235`). Step 15 pins `COMBAT_SOURCE_ENABLED = False` inside that test — its subject is what the REGISTER projection does to `trials.json`, and the combat key has its own on/off pin in `tests/test_combat.py`. |
| The degrade precedent is `roster_unavailable` / `buildings_unavailable` | Confirmed: `_GuildInputs` `:4278`, `:4292`; the buildings block in `_fetch_guild` `:4594-4639` catches `SheetStructureError`, prints `WARNING (…)` to stderr, and lets `RuntimeError` propagate. The 2026-07-25 incident is at `config.py:107-127`. `GVIZ_NO_HEADER_COLLAPSE` (`:126`) is NOT for a machine-written tab — `buildings.py:22-23` says why ("blanks the label of every numeric column"). |
| The Apps Script write path is a third format plus two tab names | Confirmed and cheaper than stated: `TAB_FORMAT` `Code.gs:80-86`, `formatOf_` `:203-208`, and the write loop at `:150-158` already does `format === 'signup' ? truthy_(src[c]) : cell_(src[c])`, so a third format inherits `cell_` (numbers stay numbers, `:212-216`) with no change to the loop. The only other edit is the error string at `:124`. `086de16` added `'buildings'` the same way. `Code.test.js` has 14 tests; `:276-294` pins "exactly the five real tabs" and `:217` pins the two-format error message — both must change. |
| The optimiser's assignment with names is in scope at `report` time | Confirmed: `doReport` (`cli.js:1560-1855`) holds `assignResult` (`:1568-1576`; the search winner under `--optimize`) and `a.merged.members`; the pins write-back at `:1821-1841` already builds `nameOf = new Map(members.map(m => [m.characterId, m.names.current]))` (`:1826-1827`) and calls `pinsFromAssignment(assignResult, {nameOf, …})`. `assignResult.assignments[i]` carries `characterId, hrid, team, trialHrid, role, label, templateId` (`render.js:779-810`; `assign.js:807`). The new writer mirrors that exact shape. `--include-names` is NOT needed: names are read from the merged members, as the pins path does. |
| `optimizer/test/blast-radius.test.js:47` guards the endpoint the new writer will hit | **Wrong.** That test reads `apps-script/Code.gs` relative to `REPO_ROOT` (`:21-23`) — **SCLIRoster's own** private-profile write endpoint (`SCLIRoster/apps-script/Code.gs:3`, `readPath: false` at `:125`), not `farm/guild/apps-script/Code.gs`. This change never touches SCLIRoster's `apps-script/`. The pre-existing failure is an uncommitted comment edit in that file (`~/pie/guild` → `~/pie/farm/guild`) and is out of scope. The one blast-radius assertion that DOES bear on us is `:42-45`: the shipping userscript must not contain the substring `optimizer/`. |
| The three invariant statements are at `pins-writeback.test.js:1-10`, `plan-implementation.md:1678-1680`, `render.js:951-952` | Two anchors drift: the test banner runs `:1-12` (the quoted sentence is `:5-6`); the markdown prose is `render.js:955-957` (`'Nothing here was written to any spreadsheet; the optimiser has no write ' + 'path to one.'`). A fourth statement exists at `plan-implementation.md:1806` ("the optimiser has no write path to any sheet"). `plan.md:706` and `:894` concern the private-sheet READ project and stay true. No test asserts the prose (`grep "write path" optimizer/test/` → nothing). |
| The secret must come from the environment or an ignored local file | The repo already has the right machinery: `optimizer/src/sources/credentials.js` loads `~/.config/scliroster/credentials.json` (`:41-42`, overridable by `SCLI_CREDENTIALS` `:44-46`), **refuses a path under `REPO_ROOT`** (`:68-74`), refuses mode ≠ 0600 (`:86-91`), validates an `/exec` URL by regex (`:51`), and exports `redact()` (`:131-140`). The combat write credentials go in that same file under two new keys (§3.2). `data/exports/` is gitignored (`.gitignore`). |
| Names on the sheet are already public | Confirmed at the sheet level: `SC Trial Signup` lists every member by name (header `User, Milking, Alchemy, Crafting, Enhancing, Swarm, Badger`, captured today), and `SC Roster` carries `name` and `characterId`. Publishing names to a machine tab adds no new class of exposure. The row this plan writes carries **no characterId** — SCLIRoster's convention 8 (`identity.js:1-33`) is intact. |
| `signup.py` ignores columns F+ by position | Confirmed: `SKILLING_COL_START = 1`, `SKILLING_COL_COUNT = 4` (`signup.py:157-158`); `parse_signup` indexes `range(1, 5)` only (`:216-231`). `draw.trial_columns` (`draw.py:209-254`) likewise. The combat pair is header cells **5 and 6** — the same fixed geometry, read by position, as the optimiser's `trialSignup.js:97` (`cols.slice(-2)`) confirms from the other side. |
| The sibling writer's stale-sign-up guard is at `mwi-guild-signup-sync.user.js:52-57` | That is the header comment. The function is `isRealWeek` at `:531-535` (rejects the `0001-`/`1970-` "never signed up" sentinels); the per-row test is `rec.signupWeekStartAt === currentWeek` at `:478`. |
| Baseline SCLIRoster: 958 tests | Confirmed today. `npm test` = `node --check scli-roster.user.js && node --test "test/*.test.js" "apps-script/**/*.test.js" "optimizer/test/**/*.test.js"` (`package.json:7`). |

## 3. The design decisions worth arguing

### 3.1 The artefact identifies a combat trial by **hrid**; the userscript derives the tile key

`trials.json["combat"]["trials"][i]["hrid"] = "/guild_combat/chameleon"`, and the script
computes `combatTileSlug(hrid) = "trial" + normSkill(hrid.split("/").pop())` →
`"trialchameleon"`, which is what BOTH of `slugOfTile`'s paths produce for that tile (the
fragment `trial_chameleon` and the label "Trial Chameleon").

Rejected: publishing the display form `"Trial Chameleon"` so that `normSkill` falls through
unchanged. It is the cheaper edit — zero new script code — and it is the wrong contract.
The hrid is the game's own identifier and it is what the two WebSocket fields the script
must compare against already carry: `guildWeeklyTrialSet.combatHrids` (the freshness set)
and `signedUpCombatTrialHrid` (the mismatch). With hrids in the artefact, both comparisons
are string equality on the same vocabulary with no normalisation on either side; with the
display form, both would pass through `normSkill` and a Title-Case mapping the game does not
promise. The display label is what the game renders and may rename; the hrid slug is what
the sprite fragment is derived from. On the sheet, an hrid column admits a structural guard
(`startswith("/guild_combat/")`) that a display name cannot. The whole cost is one three-line
function in the script and a lowercase-alnum normaliser on the Python cross-check ("Swarm"
from the sign-up header vs `swarm` from the hrid; the sibling writes those headers with
`prettify(hrid)` at `mwi-guild-signup-sync.user.js:521`, so the two agree for every boss
in the nine-name vocabulary).

### 3.2 The bridge is `report --publish-combat`, one row per seated member, to a machine-owned tab

The writer hangs off `report` exactly as `--write-pins` does (`cli.js:1821-1841`): the rows
are built from the SAME `assignResult` the report describes, by a pure function shaped like
`pinsFromAssignment` (`pins.js`), and posted only when the flag is passed. That gives three
properties for free: the sheet can never disagree with the report it was written beside
(same object, same run); it works with and without `--optimize` (winner or incumbent, as the
report itself chooses at `:1571-1576`); and the operator's weekly loop stays one command.

Rejected: a standalone `publish-combat --from <report.json>`. The default report is
redacted (`includeNames: false` → `roster[i]` carries `hrid: "m1015"` and no `name`), so the
file cannot be the source without `--include-names` and a second consumer of the report
schema; a second solve instead of a file could differ from the report if pins moved between
runs. Rejected: keying rows by `characterId` — `trials.json` names members by name, the
script matches by `normName` (`:315-317`), and the id is the one thing SCLIRoster promises
never leaves (`render.js:779-800`, `cli.js:1774-1790`). The writer uses `names.current`
(the roster harvest's in-game name at capture, the closest thing to what
`init_character_data` reports) and **refuses** a seat with no name rather than guessing,
counting it in the CLI output.

Rejected routes, one line each, as the user settled them:
- **Re-reading the officers' hand-maintained "Trial Assignments" tab.** Rebuilt three times,
  downstream of this project's own output (`draw.py:31-38`), and the brief's reason the
  2026-07-25 deploy died.
- **Publishing the F–G sign-up ticks.** They are what members PICKED, not what the optimiser
  ASSIGNED; the whole point is to show the difference.
- **Publishing `data/exports/report-*.json` as a second artefact.** A second fetch, a second
  host (`@connect`), a second freshness path, and a redacted-by-default file.
- **Reading `signedUpCombatTrialHrid` off the WebSocket as the glow source.** It is the
  sign-up, which the game already marks (`GuildPanel_trialTileMine`); glowing it says
  nothing new. It IS read — as the mismatch's other half.

### 3.3 One flag gates the fetch and the attach; provenance is not touched

`config.COMBAT_SOURCE_ENABLED` is checked in `_fetch_combat` (no fetch when off, like
`ROSTER_SOURCE_ENABLED` at `build.py:4537`) AND in `_write_guild` (no key when off). Off is
therefore byte-identical to today's `trials.json` — including `provenance`, because this
plan adds nothing to `_provenance_block` (`:187-…`). The buildings work did add
`buildings_*` keys there unconditionally, for `data.json`/`signup.json` readers; combat has
exactly one consumer, `trials.json`, and the `combat` block carries its own
`available`/`unavailable`, so a provenance entry would be a second place for the same fact.

Secret placement: two new optional keys in the **existing** `~/.config/scliroster/credentials.json`
— `combatWriteUrl` (farm/guild's `/exec`, validated by the same `EXEC_RE`) and
`combatWriteSecret` (farm/guild's `SHARED_SECRET`). Same file, same outside-the-tree and
0600 refusals, one place to rotate. `farm/guild/apps-script/Code.gs:71` keeps its
`PASTE_A_LONG_RANDOM_SECRET_HERE` placeholder; the deployed copy is edited in the Apps
Script editor, never in the tree (as today).

## 4. The contracts, to the cell

### 4.1 The sheet tab — `SC Combat Teams` / `LI Combat Teams` (public sheet `1b5_zID6K4WRaFXnBMJijSEXr_4l2gi40eFKxuvRJQAE`)

Created by hand, empty. Written ONLY by `report --publish-combat`, through `doPost`
(clear-and-rewrite from A1, `Code.gs:160-172`). Row 1 is the header, verbatim; one row per
**seated member**; no blank rows; rows sorted by `Team` then `Slot` so a rewrite of the same
recommendation diffs clean.

| col | header (exact) | type | value | source |
|---|---|---|---|---|
| A (0) | `Member` | text | the member's current in-game name | `merged.members[].names.current` |
| B (1) | `Trial Hrid` | text | `/guild_combat/<boss>` | `assignments[i].trialHrid` |
| C (2) | `Team` | text | `SC Team 1` etc. | `assignments[i].team` (= `guild.tabs.teams[]`) |
| D (3) | `Role` | text | the template role id, e.g. `cursed`, `tank`, `healer_blooming` | `assignments[i].role` |
| E (4) | `Slot` | text | the slot label, e.g. `cursed 1` | `assignments[i].label` |
| F (5) | `Guild Id` | **number** | `4` / `240` | `guild.guildId` — the wrong-guild guard |
| G (6) | `Generated At` | text | ISO-8601 UTC, identical on every row | `model.generatedAt` |

`header[0] === "Member"` is the format sentinel (`formatOf_` → `'combat'`). Both tabs are
`'combat'` in `TAB_FORMAT`; a combat block is refused on any other tab and any other block is
refused on these (the existing interlock, `Code.gs:126-128`). MIN_COLS (3) is satisfied.
`Guild Id` lands as a numeric cell via `cell_` (`:212-216`).

### 4.2 `trials.json["combat"]` — `object`, present iff `config.COMBAT_SOURCE_ENABLED`

| key | type | value |
|---|---|---|
| `available` | `bool` | `True` iff the tab was read, non-empty, structurally valid, stamped with this guild's id, and its two hrids equal (as a set) the last two header cells of this guild's own sign-up tab |
| `unavailable` | `str` | `""` when available; otherwise the reason, verbatim the text of the CI `WARNING` — one of: never written · could not be read (with the `SheetStructureError`) · stale (both sets named) · cannot cross-check (sign-up header unreadable) · flag off |
| `source` | `str` | the tab name (`config.COMBAT_TABS[key]`) |
| `generated_at` | `str` | the tab's `Generated At` (oldest across rows, as `buildings.captured_at` does); `""` when unavailable |
| `trials` | `list[object]` | `[]` when unavailable; else one per team in **tab order** (first-seen order of `(Trial Hrid, Team)` walking rows top to bottom) |

Each `trials[i]`:

| key | type | value |
|---|---|---|
| `hrid` | `str` | `/guild_combat/<boss>` |
| `team` | `str` | `SC Team 1` etc. |
| `party_size` | `int` | `len(roster)` |
| `roster` | `list[object]` | `{"name": str, "role": str, "slot": str}` in tab (slot) order |

Consumer recipe (the userscript): `art.combat?.available` gates everything;
`new Set(art.combat.trials.map(t => t.hrid))` must equal `guildWeeklyTrialSet.combatHrids`
as a set or nothing glows; `trials.find(t => t.roster.some(r => normName(r.name) === me))`
gives the assignment; `combatTileSlug(t.hrid)` gives the tile key. An artefact **without**
the key (older build, flag off) means "no combat data in this artefact" and is not an error.
The key is **not** compared with `week_date`, `signupWeekStartAt` or `currentWeekStartAt`.

### 4.3 The Apps Script payload (unchanged shape, `Code.gs:96-138`)

`POST <farm/guild /exec>` with JSON body
`{ "secret": <SHARED_SECRET>, "tab": "SC Combat Teams", "header": [7 cells of §4.1], "rows": [[7 cells], …] }`.
Reply `{ ok: true, tab, format: "combat", wroteRows, columns: 7, clearedRows, clearedCols }`
or `{ ok: false, error }` (`:174-185`). The writer treats anything but `ok: true` JSON as a
refusal and names the fix for `unauthorised` / `tab not found` / `format mismatch`.

### 4.4 What does not change

- `trials.json`'s existing keys, `trials[]`, `bench`, `provenance`: unchanged in name, type,
  order and value. Pinned by the flag test (§8).
- `data.json`, `index.html`, `trials.html`, `signup.json`, `signup.html`, `trials-maxbuffs.*`:
  untouched. The register does NOT carry combat — a separate, additive follow-up behind its
  own flag if ever wanted (the brief's scope note).
- `src/trials.py`, `src/signup.py`, `src/draw.py`, `src/roster.py`, `src/reader.py`,
  `_attach_week`, `_provenance_block`, `.github/workflows/deploy.yml`: untouched.
- SCLIRoster: `scripts/publish.sh`, `apps-script/**` (its OWN endpoints), the `.md`/`.json`
  report redaction, `data/pins.json` handling: untouched.
- The skilling glow, freshness guard and lookup (`recompute` `:822-848`): unchanged; combat
  runs after them.

## 5. Degraded paths — what each layer does when the one before it is missing

| situation | decided where | `trials.json["combat"]` | userscript |
|---|---|---|---|
| Flag off | `_fetch_combat` / `_write_guild` | **no key** (byte-identical) | "this artefact carries no combat data" — skilling glow as today |
| Tabs not yet created | gviz serves the FIRST tab → header guard | `available: false`, reason names the guard failure and says to create the tab | same, showing the reason |
| Tab exists, never written (0 bytes / header only) | `parse_combat` → `observed=False` | `available: false`, "has never been written — it fills the first time the optimiser runs `report --publish-combat`" | same |
| Officer typed in the tab / writer header changed / other guild's id / non-combat hrid | `SheetStructureError` | `available: false`, the error text | same |
| Optimiser wrote last week's pair; sign-up tab refreshed | cross-check | `available: false`, "stale: the tab lists [x, y], the sign-up tab lists [a, b]" | same; AND its own set guard would refuse anyway |
| Sign-up tab not yet refreshed; optimiser wrote the new pair | cross-check | `available: false`, same text (both sets named — the message does not guess which side is stale) | same |
| Sign-up tab header not in tick-box format (`trial_columns` raised) | `signup_combat_pair` raises | `available: false`, "cannot cross-check" | same |
| Network `RuntimeError` on the combat fetch | propagates, as for every other tab (`build.py:4552`, `:4593`, `:4645`) | build fails — **unchanged behaviour class**; the same host serves the member tab, which would have failed first | — |
| Artefact current for skilling, combat block current | — | `available: true` | both glows |
| Draw rotated since the build | script's skilling set guard (`:822-836`) | (whatever was built) | nothing glows, combat included — the artefact predates the rotation |
| `combatHrids` differ from the block's hrids | script's combat set guard | — | combat glows nothing, says so; skilling unaffected |
| Cold page load, no Members panel opened | no sign-up frame | — | verdict `unknown`: "sign-up not yet known — open Guild ▸ Members" |
| Member's last sign-up is for a previous week | `signupWeekStartAt !== guild.currentWeekStartAt` | — | verdict `stale`, never `mismatch` |
| Character switch to another guild | `ingest` `:672-678` | — | combat assignment and sign-up cleared with the skilling one |

The build ships in every row: `_fetch_combat` catches `SheetStructureError`, `parse_combat`
raises on nothing the sheet can serve except through that class, and the attach is dict
work over fields the dataclass always has.

## 6. Files touched

### Layer 1 — `/Users/morgan/pie/farm/guild/apps-script/`
| file | change |
|---|---|
| `Code.gs` | Header comment `:20-29` (THREE formats), setup step 5 `:46-57` (two more tabs, written by the optimiser), `TAB_FORMAT` comment `:73-79` and map `:80-86` (+2 entries), `MIN_COLS` comment `:89-94` (a combat block is a fixed 7), error string `:124`, `formatOf_` `:203-208` (+1 line). ~20 lines. |
| `Code.test.js` | Fixtures `C_HEADER`/`combatRows()`; +5 tests; edit `:217` regex and `:276-294` (seven tabs). |
| `README.md` | A third block diagram; the writer is the optimiser (a Node CLI), not the in-game module; "machine-owned — do not type in it". |

### Layer 2 — `/Users/morgan/pie/SCLIRoster/`
| file | change |
|---|---|
| `optimizer/src/publish/combatTab.js` | **NEW.** `HEADER`, `TAB_BY_GUILD`, `combatRowsFromAssignment`, `publishTargetFor`, `postCombatTab`. ~120 lines. |
| `optimizer/src/sources/credentials.js` | Factor the path/mode/JSON checks of `loadCredentials` (`:62-98`) into `readSecretFile(p, howto)`; add `loadCombatWriteCredentials`. `loadCredentials`'s messages verbatim. ~40 lines. |
| `optimizer/cli.js` | `report` flag plumbing `:2997-3012` (+1), `doReport` side effect after `:1852` (~25 lines), `reportReport` print after `:1957` (~8), `USAGE` `:2625+` (+3 lines). |
| `optimizer/test/combat-tab.test.js` | **NEW.** ~12 tests (§8). |
| `optimizer/test/credentials.test.js` | +2 tests for the new loader. |
| `optimizer/test/pins-writeback.test.js` | Banner `:1-12`: the amended invariant. |
| `optimizer/src/report/render.js` | Prose `:955-957`. |
| `plan-implementation.md` | `:1678-1680` and `:1806`. |
| `optimizer/README.md` | "Use" section: the flag, the preview mode, the credentials keys, the invariant. |

### Layer 3 — `/Users/morgan/pie/farm/guild/`
| file | change |
|---|---|
| `src/config.py` | `COMBAT_SOURCE_ENABLED`, `COMBAT_TABS`, `COMBAT_SENTINEL_HEADERS` after `BUILDINGS_SENTINEL_HEADERS` (`:1663-1670`). ~35 lines incl. comments. |
| `src/combat.py` | **NEW.** The reader, mirroring `src/buildings.py`. ~220 lines. |
| `src/build.py` | Import beside `buildings_model`; `GuildSite.combat_tab` after `:158`; `_GuildInputs.combat`/`combat_unavailable` after `:4292`; `signup_csv = ""` before the `try` at `:4647`; new `_fetch_combat(site, signup_csv)` before `_fetch_guild`; one call before `return _GuildInputs(` at `:4693` (+2 kwargs); `_combat_block(inputs, site)` before `_write_guild`; the attach after `:4896`; a `combat_note` clause in `_summary_line` beside `:4845-4850`. ~110 lines; no signature changes. |
| `tests/test_combat.py` | **NEW.** 15 tests (§8). |
| `tests/test_register_week.py` | `:229-257`: pin `COMBAT_SOURCE_ENABLED` off, with a comment. 3 lines. |
| `README.md` | New `### trials.json carries the combat teams` after `:535` (before `## Sign-up optimiser`). ~30 lines. |

### Layer 4 — `/Users/morgan/pie/SCLIRoster/scli-roster.user.js` (+ tests)
| file | change |
|---|---|
| `scli-roster.user.js` | `@version 0.4.1 → 0.5.0` (`:4`); header `:38-46`, `:91-103`, `:106-110`; `state` `:530-566` (+6 fields); `ingest` `:653-704` (+3 reads, +2 clears); new `ingestSignup`; `maybeRefresh` no-url branch `:762` (+1 clear); `recompute` `:794-857` (+call); new `combatTileSlug`, `signupVerdict`, `recomputeCombat`; `decorate` `:2078-2100` (Map of wants + mismatch class); CSS `:2268+` (`.scli-mismatch`); `buildPanel` rows `:2713-2718` (+2 rows, +1 verdict line); `paint` `:2966-2988`; registration after `:3293`; handle `:3311+` (`dump`, `Ui`). ~220 lines. |
| `test/combat.test.js` | **NEW.** 14 tests (§8). |
| `todo.md` | `:386-396`: the two items closed, with the version. |

## 7. Steps — ordered across the four layers, each with its verification

The order is load-bearing: the sheet contract (L1) must exist before anything writes it
(L2); the reader (L3) must exist before the artefact key means anything; the userscript
(L4) reads the key last. Each layer is independently inert without the next (§5), so the
work can stop after any step and ship.

**Step 0 — checkpoints and baselines.** In each repo, `git rev-parse HEAD` as the rollback
anchor (`086de16`, `fab85ab`). Re-run both baselines once so the numbers below have a
comparison point. Stage only this change's files at each commit — `git add -p` on
`src/config.py`, `src/build.py`, `README.md` (farm/guild) and on `plan-implementation.md`
(SCLIRoster), which carry unrelated pending edits.

### Layer 1 — the endpoint accepts a `combat` block

**Step 1 — `apps-script/Code.gs`** ~15 min

- `:20-29`: "THREE BLOCK FORMATS, one per tab" and a third line:
  `'combat'     col 0 = "Member",   then Trial Hrid, Team, Role, Slot, Guild Id, Generated At`
  with one sentence: written by the OPTIMISER (`~/pie/SCLIRoster`, `report --publish-combat`),
  a Node CLI — not by the in-game module — and read by `guild/src/combat.py`.
- `:46-57` step 5: add `"SC Combat Teams"` / `"LI Combat Teams"` — "empty is fine; the
  first optimiser publish fills them. MACHINE-OWNED: nobody types in them; every publish
  rewrites them from A1."
- `:73-79`: `//   'combat'    header[0] = "Member"    the optimiser's combat teams (SCLIRoster)`.
- `:80-86`:
  ```js
  var TAB_FORMAT = {
    'chikenz-test':    'signup',
    'SC Trial Signup': 'signup',
    'LI Trial Signup': 'signup',
    'SC Buildings':    'buildings',
    'LI Buildings':    'buildings',
    'SC Combat Teams': 'combat',
    'LI Combat Teams': 'combat'
  };
  ```
- `:89-94`: "A buildings block is a fixed 6, a combat block a fixed 7."
- `:124`: `'bad header: col 0 must be "User" (sign-ups), "Building" (levels) or "Member" (combat teams)'`.
- `:203-208`: add `if (h0 === 'Member') return 'combat';` before `return null;`.

Verify: `cd /Users/morgan/pie/farm/guild && node --test apps-script/Code.test.js` → 2 fail
(the two pins that must change: `:207-219` message, `:276-294` five tabs), 12 pass.

**Step 2 — `apps-script/Code.test.js`** ~25 min

Fixtures after `:133`:
```js
const C_HEADER = ["Member", "Trial Hrid", "Team", "Role", "Slot", "Guild Id", "Generated At"];
function combatRows(guildId = 4, at = AT) {
    return [
        ["Yedic",  "/guild_combat/chameleon", "SC Team 1", "tank",   "tank 1",   guildId, at],
        ["Pipsqueak", "/guild_combat/chameleon", "SC Team 1", "cursed", "cursed 1", guildId, at],
        ["IronOwl", "/guild_combat/hedgehog",  "SC Team 2", "healer_blooming", "healer_blooming 1", guildId, at],
    ];
}
```
New tests: `a combat block is written to its own tab, with Guild Id as a real number and
everything else text` (asserts `res.format === "combat"`, `columns === 7`, `_grid[0][0] ===
"Member"`, `typeof _grid[1][5] === "number"`, `_grid[1][1] === "/guild_combat/chameleon"`);
`a COMBAT block sent to a SIGN-UP tab is refused, and the roster survives` (byte-identical
grid, `/format mismatch/`, `/combat block/`); `a SIGN-UP block sent to a COMBAT tab is
refused`; `a BUILDINGS block sent to a COMBAT tab is refused` (the interlock is three-way);
`the combat block goes to either guild's tab, independently`. Edit `:217` to the new
message; edit `:276-294` to seven tabs and the seven-entry `tabFormats`, renaming the test
`doGet lists exactly the seven real tabs, with their formats`.

Verify: `node --test apps-script/Code.test.js` → 19 passed, 0 failed.

**Step 3 — `apps-script/README.md`** ~10 min

After `:30`: a third block diagram — `SCLIRoster optimiser (Node) · report --publish-combat
→ POST {secret, tab, header, rows} → "SC Combat Teams" / "LI Combat Teams"`; in
"One-time setup" step 1 add the two tabs as **empty**; in "Safety notes" a bullet
"Machine-owned tabs: `SC/LI Buildings` and `SC/LI Combat Teams` are rewritten from A1 on
every write. Anything typed into them is lost on the next write, and the Python reader
refuses a hand-edited header (`combat.py`) rather than parse it." Point the optimiser's
credentials at this README's step 3 (the secret) and step 4 (the `/exec` URL).

Verify: read back; the tab names match step 1 and step 12 exactly (three places, one string).

**Step 4 — deploy (manual, in the browser)** ~10 min

1. In the guild spreadsheet, add two empty tabs named exactly `SC Combat Teams` and
   `LI Combat Teams`.
2. Extensions → Apps Script → paste `Code.gs` (with the real `SHARED_SECRET` re-applied in
   the editor — the tree keeps the placeholder) → Deploy → Manage deployments → edit → New
   version → Deploy (`apps-script/README.md:108-112`).

Verify: open the `/exec` URL → `allowedTabs` has 7 entries and `tabFormats["SC Combat Teams"] === "combat"`.
Then `curl -s "https://docs.google.com/spreadsheets/d/1b5_zID6K4WRaFXnBMJijSEXr_4l2gi40eFKxuvRJQAE/gviz/tq?tqx=out:csv&sheet=SC%20Combat%20Teams" | wc -c` → `0`
(an empty tab serves zero bytes; a missing one would serve the first tab's ~3.5 KB — that is
the difference `parse_combat` relies on).

### Layer 2 — the optimiser writes it

**Step 5 — `optimizer/src/sources/credentials.js`: a second loader over the same file** ~20 min

Factor `:65-98` (outside-the-tree, 0600, JSON parse) into
`function readSecretFile(p, howto) → body`, keeping every message string verbatim (the tests
at `credentials.test.js:56-121` pin them). `loadCredentials` calls it, then validates
`profilesUrl`/`readToken` exactly as now (`:100-121`). Add:

```js
const COMBAT_HOWTO = 'See ~/pie/farm/guild/apps-script/README.md § "One-time setup" '
    + '(step 3 is the secret, step 4 the /exec URL).';

/**
 * The ONE write credential this tool holds: farm/guild's sign-up/buildings/combat
 * endpoint on the PUBLIC sheet. Two keys in the same file as the read credentials,
 * so there is one file to keep at 0600 and one place to rotate.
 * @returns {{combatWriteUrl: string, combatWriteSecret: string, path: string}}
 */
export function loadCombatWriteCredentials({ file = null, env = process.env } = {}) {
    const p = path.resolve(file || credentialsPath(env));
    const body = readSecretFile(p, COMBAT_HOWTO);
    const combatWriteUrl = typeof body?.combatWriteUrl === 'string' ? body.combatWriteUrl.trim() : '';
    const combatWriteSecret = typeof body?.combatWriteSecret === 'string' ? body.combatWriteSecret.trim() : '';
    if (!combatWriteUrl || !combatWriteSecret) {
        const missing = [!combatWriteUrl && 'combatWriteUrl', !combatWriteSecret && 'combatWriteSecret']
            .filter(Boolean).join(' and ');
        throw new Error(`${p} is missing ${missing}. ${COMBAT_HOWTO}`);
    }
    if (!EXEC_RE.test(combatWriteUrl)) {
        throw new Error(`${p}: combatWriteUrl is not an Apps Script /exec URL. ${COMBAT_HOWTO}`);
    }
    return { combatWriteUrl, combatWriteSecret, path: p };
}
```

Verify: `node --test optimizer/test/credentials.test.js` → all existing pass unchanged.

**Step 6 — `optimizer/src/publish/combatTab.js` (new)** ~40 min

```js
// combatTab.js — THE OPTIMISER'S ONLY SPREADSHEET WRITE PATH, and its whole extent.
// Writes the recommended combat teams, one row per seated member, to a MACHINE-OWNED
// tab of the PUBLIC guild sheet through farm/guild's Apps Script endpoint. It writes
// nowhere else: not to an officer-maintained tab (the endpoint's TAB_FORMAT refuses a
// 'combat' block anywhere but these two tabs), and never to the private sheet (no
// URL for it exists in this module, and SHEETS.private is not imported). Until
// 2026-09-09 the invariant read "the optimiser has no write path to any spreadsheet";
// this file is the deliberate, narrowed replacement, and optimizer/test/combat-tab.test.js
// pins its extent.
import { redact } from '../sources/credentials.js';

export const HEADER = Object.freeze(
    ['Member', 'Trial Hrid', 'Team', 'Role', 'Slot', 'Guild Id', 'Generated At']);
/** Must equal guild/src/config.py COMBAT_TABS and guild/apps-script/Code.gs TAB_FORMAT. */
export const TAB_BY_GUILD = Object.freeze({ sc: 'SC Combat Teams', li: 'LI Combat Teams' });
export const COMBAT_HRID_PREFIX = '/guild_combat/';

export function publishTargetFor(guildSlug) {
    const tab = TAB_BY_GUILD[guildSlug];
    if (!tab) throw new Error(`no machine-owned combat tab for guild "${guildSlug}"; `
        + `the optimiser writes only ${Object.values(TAB_BY_GUILD).join(' / ')}`);
    return tab;
}

/** One row per NAMED seat. A seat whose member has no current name is NOT guessed at:
 *  it is returned in `unnamed` and the CLI says so. No characterId enters a row. */
export function combatRowsFromAssignment(assignResult, { nameOf, guildId, generatedAt }) {
    const rows = []; const unnamed = [];
    for (const a of assignResult.assignments) {
        const name = nameOf.get(a.characterId) || null;
        if (!name) { unnamed.push(a.characterId); continue; }
        if (!String(a.trialHrid || '').startsWith(COMBAT_HRID_PREFIX)) {
            throw new Error(`seat ${a.label} on ${a.team} has trialHrid ${JSON.stringify(a.trialHrid)}, not a combat trial`);
        }
        rows.push([name, a.trialHrid, a.team, a.role, a.label, guildId, generatedAt]);
    }
    rows.sort((x, y) => String(x[2]).localeCompare(String(y[2])) || String(x[4]).localeCompare(String(y[4])));
    return { header: [...HEADER], rows, unnamed };
}

export async function postCombatTab({ url, secret, tab, header, rows,
                                      fetchImpl = globalThis.fetch, timeoutMs = 20_000 }) {
    // body shape = guild/apps-script/Code.gs doPost, verbatim: { secret, tab, header, rows }
    …AbortController timeout; POST application/json; non-2xx → throw (redacted);
    …HTML body → throw "sign-in page / sharing"; JSON.ok !== true → throw naming the fix for
    …'unauthorised' (secret), 'tab not found' (create it), 'format mismatch' (wrong tab).
    return { tab: res.tab, format: res.format, wroteRows: res.wroteRows, columns: res.columns };
}
```
Every thrown message passes through `redact(msg, secret)` (`credentials.js:131-140`).

Verify: `node --check optimizer/src/publish/combatTab.js`; step 8's tests.

**Step 7 — `optimizer/cli.js`** ~25 min

- Import `loadCombatWriteCredentials` (`:28`) and the three exports of `publish/combatTab.js`.
- `report` flags (`:2997-3012`): `publishCombat: flags['publish-combat'] === undefined ? false : flags['publish-combat'],`
  (`true` posts; the string `"preview"` writes the block to disk and posts nothing —
  `parseArgs` `:88-100` yields both).
- `doReport`, after the pins block `:1821-1852` and before `return` `:1854`:
  ```js
  // --- the combat teams, PUBLISHED to the machine-owned tab (2026-09-09) -----------
  // The optimiser's only spreadsheet write path. From the SAME assignResult the report
  // describes, so the sheet can never disagree with the document beside it. Names,
  // and NO characterId: the destination is the public sheet's own machine tab, where
  // "SC Trial Signup" already lists every member by name. Not assertNoPII-scanned for
  // names, for that reason; the preview file IS scanned for the id half.
  let published = null;
  if (opts.publishCombat) {
      const nameOf = new Map(a.merged.members.map(
          (m) => [m.characterId, (m.names && m.names.current) || null]));
      const block = combatRowsFromAssignment(assignResult,
          { nameOf, guildId: guild.guildId, generatedAt: model.generatedAt });
      const tab = publishTargetFor(guild.slug);
      if (opts.publishCombat === 'preview') {
          const file = path.join(outDir, `combat-${safeSlug(guild.slug)}-${safeSlug(a.cycle.id)}.json`);
          const text = `${JSON.stringify({ tab, ...block }, null, 2)}\n`;
          assertNoPII(text, { members: [], where: 'the combat preview' });   // id half only
          fs.mkdirSync(outDir, { recursive: true }); fs.writeFileSync(file, text);
          published = { preview: file, tab, rows: block.rows.length, unnamed: block.unnamed };
      } else {
          const creds = loadCombatWriteCredentials();
          const res = await postCombatTab({ url: creds.combatWriteUrl, secret: creds.combatWriteSecret,
                                            tab, header: block.header, rows: block.rows });
          published = { tab: res.tab, wroteRows: res.wroteRows, unnamed: block.unnamed };
      }
  }
  ```
  and add `published` to the returned object.
- `reportReport` after `:1957`: print `combat  <tab>  <n> row(s) written` or `combat  preview → <file>`,
  and `<k> seat(s) had no current name and were NOT published: <ids>` when `unnamed.length`.
- `USAGE` (`:2625+`), under the report flags:
  ```
  --publish-combat   for report: write the recommended combat teams, one row per
                     seated member, to this guild's MACHINE-OWNED tab on the public
                     sheet ("SC Combat Teams" / "LI Combat Teams") through farm/guild's
                     Apps Script endpoint. Needs combatWriteUrl + combatWriteSecret in
                     ~/.config/scliroster/credentials.json. The only spreadsheet write
                     this tool has. --publish-combat=preview writes the block to
                     data/exports/ and posts nothing.
  ```

Verify: `node --check optimizer/cli.js`; `node optimizer/cli.js report --guild sc --offline --publish-combat=preview`
→ exit 0, prints `combat  preview → data/exports/combat-sc-<cycle>.json`; the file's `header`
equals §4.1 and every row has 7 cells.

**Step 8 — `optimizer/test/combat-tab.test.js` (new) and two credentials tests** ~35 min

See §8. Verify: `node --test optimizer/test/combat-tab.test.js optimizer/test/credentials.test.js` → all pass.

**Step 9 — amend the invariant, deliberately, in words** ~15 min

Replace, in each place, "the optimiser has no write path to any spreadsheet" with the
narrower statement that is now true:

> The optimiser writes to exactly one place on any spreadsheet: the machine-owned combat
> tabs (`SC Combat Teams` / `LI Combat Teams`) on the PUBLIC sheet, through farm/guild's
> Apps Script endpoint, from `report --publish-combat`. Never to an officer-maintained tab
> (the endpoint's `TAB_FORMAT` refuses it), never to the private sheet (`publish/` imports no
> URL for it), and never anything but names — no `characterId` leaves.

- `optimizer/test/pins-writeback.test.js:1-12` — the banner (`:5-6` today).
- `plan-implementation.md:1678-1680` and `:1806` — with the date and the reason (the
  userscript needs the combat assignment and `trials.json` is the one artefact it fetches).
- `optimizer/src/report/render.js:955-957` — the markdown line becomes
  `'This document was written to no spreadsheet. The optimiser\'s one spreadsheet write is '
   + 'the machine-owned combat teams tab, and only when `report --publish-combat` is passed.'`
- `optimizer/README.md` "Use": the flag, the preview, the credentials keys, the invariant.

Verify: `grep -rn "no write path to any" optimizer/ plan-implementation.md` → only the
historical mentions that describe the READ project (`plan-implementation.md:1257`,
`:1849`) remain; `npm test` → 957+N pass, the same single pre-existing failure.

**Step 10 — the preview, on live data** ~5 min

```bash
cd /Users/morgan/pie/SCLIRoster && node optimizer/cli.js report --guild sc --publish-combat=preview
python3 -c "import json;d=json.load(open(sorted(__import__('glob').glob('data/exports/combat-sc-*.json'))[-1]));print(d['tab'],len(d['rows']),d['unnamed']);assert d['header']==['Member','Trial Hrid','Team','Role','Slot','Guild Id','Generated At'];assert all(len(r)==7 and r[1].startswith('/guild_combat/') and r[5]==4 for r in d['rows'])"
```
Expected: `SC Combat Teams`, a row count equal to the report's seated count (`teams[].partySize` summed), `unnamed == []`.

**Step 11 — the first real write** ~10 min

Add `combatWriteUrl` and `combatWriteSecret` to `~/.config/scliroster/credentials.json`
(mode stays 0600). Then `node optimizer/cli.js report --guild sc --publish-combat`.

Verify: the CLI prints `combat  SC Combat Teams  <n> row(s) written`; and
```bash
curl -s "https://docs.google.com/spreadsheets/d/1b5_zID6K4WRaFXnBMJijSEXr_4l2gi40eFKxuvRJQAE/gviz/tq?tqx=out:csv&sheet=SC%20Combat%20Teams" | head -3
```
→ line 1 is `"Member","Trial Hrid","Team","Role","Slot","Guild Id","Generated At"`, line 2 a
real member. Repeat for `--guild li` once LI's tab exists. (Do not run `--optimize` for the
smoke test; the incumbent re-solve is what the report publishes without it, `:1568`.)

### Layer 3 — farm/guild reads it into `trials.json`

**Step 12 — `src/config.py`, after `BUILDINGS_SENTINEL_HEADERS` (`:1670`)** ~10 min

```python
# --- Combat teams: the optimiser's ONE write to the sheet (per-guild machine tab) ----
# NEW 2026-09-09. The combat-trial optimiser in ~/pie/SCLIRoster publishes its
# recommended teams — one row per seated member — through the same Apps Script
# endpoint in apps-script/ that the sign-up and buildings blocks use, to a per-guild
# tab of the public sheet. Header (fixed, seven columns, guarded by equals below):
#   Member | Trial Hrid | Team | Role | Slot | Guild Id | Generated At
# Parsed by src/combat.py and attached to trials.json as a top-level `combat` key, for
# the in-game userscript that glows a member's assigned tiles. NON-REQUIRED: any failure
# degrades to `available: false` with the reason, and never stops the deploy — SC is
# `required`, and the 2026-07-25 incident above is what a required parse failure costs.
#
# THE TABS ARE MACHINE-OWNED AND START EMPTY. An empty tab is a normal state (the
# optimiser has not published yet); a hand-edited one fails the header guard loudly.
# DO NOT append GVIZ_NO_HEADER_COLLAPSE: one clean header row, exactly what gviz's
# default collapse hands over (see that constant's note, and buildings.py's).
#
# False is the one-line rollback: no fetch, no `combat` key — trials.json byte-identical,
# pinned by tests/test_combat.py::test_flag_off_is_byte_identical_and_on_is_additive.
COMBAT_SOURCE_ENABLED = True

COMBAT_TABS = {
    "sc": "SC Combat Teams",
    "li": "LI Combat Teams",
}

# gviz wrong-tab / structure guard for a Combat Teams tab, equals throughout (machine-
# written, no merged junk). gviz serves the FIRST tab for an unknown name (measured
# 2026-09-09), so this is mandatory, not defensive. Must match SCLIRoster
# optimizer/src/publish/combatTab.js HEADER and apps-script/Code.gs's 'combat' format.
COMBAT_SENTINEL_HEADERS = {
    0: ("equals", "Member"),
    1: ("equals", "Trial Hrid"),
    2: ("equals", "Team"),
    3: ("equals", "Role"),
    4: ("equals", "Slot"),
    5: ("equals", "Guild Id"),
    6: ("equals", "Generated At"),
}
```

Verify: `.venv/bin/python -c "from src import config; assert config.COMBAT_SOURCE_ENABLED is True and len(config.COMBAT_SENTINEL_HEADERS)==7"`.

**Step 13 — `src/combat.py` (new), the shape of `src/buildings.py`** ~50 min

Module docstring: what the tab is, who writes it, the three outcomes (observed · unobserved
· malformed, `buildings.py:29-40`), the cross-check, and the `GVIZ_NO_HEADER_COLLAPSE`
prohibition. Then:

```python
from . import config, draw as draw_model
from .reader import SheetStructureError, _cell, _to_int

COL_NAME, COL_HRID, COL_TEAM, COL_ROLE, COL_SLOT, COL_GUILD_ID, COL_GENERATED_AT = range(7)
COMBAT_HRID_PREFIX = "/guild_combat/"
# The two combat columns of a sign-up tab are the two AFTER the fixed skilling block —
# spreadsheet F–G, 0-based 5..6 — the geometry signup.py and draw.py read against.
COMBAT_PAIR_COL_START = draw_model.SKILLING_COL_START + draw_model.EXPECTED_TRIALS   # 5
COMBAT_PAIR_COUNT = 2

@dataclass
class CombatSeat:  name: str; role: str; slot: str
@dataclass
class CombatTeam:
    hrid: str; team: str; roster: list[CombatSeat] = field(default_factory=list)
    def to_dict(self) -> dict:  # {"hrid","team","party_size","roster":[{name,role,slot}]}
@dataclass
class GuildCombat:
    tab: str; guild_key: str; observed: bool
    generated_at: str = ""                      # OLDEST stamp across rows, as buildings does
    teams: list[CombatTeam] = field(default_factory=list)
    @property
    def hrids(self) -> set[str]
    def to_dict(self) -> dict

def norm_trial(text: str) -> str:
    """'Swarm' -> 'swarm'; '/guild_combat/swarm' -> 'swarm'. Lowercase alphanumerics of the
    last path segment — the label the sibling writer prettifies from the hrid, and the hrid,
    meet here."""
    return re.sub(r"[^a-z0-9]", "", text.rsplit("/", 1)[-1].lower())

def fetch_combat_csv(tab_name: str) -> str          # = buildings.fetch_buildings_csv, same 401/403 text
def _validate_combat_header(header, tab) -> None    # equals x7 via config.COMBAT_SENTINEL_HEADERS
def _check_guild_id(raw, guild_key, tab, row_no)    # = buildings._check_guild_id, same message shape
def parse_combat(csv_text: str, guild_key: str, tab: str = "") -> GuildCombat
    # "" / "\n" / header-only -> observed=False. Else validate header; per row: name must be
    # non-empty; hrid must start with COMBAT_HRID_PREFIX else SheetStructureError; guild id
    # checked; teams grouped by (hrid, team) in first-seen order; generated_at = min(stamps).
def scrape_combat_tab(tab_name: str, guild_key: str) -> GuildCombat
def signup_combat_pair(csv_text: str, tab_label: str) -> list[str]
    # header cells 5..6 stripped; raises SheetStructureError if the header has < 7 cells,
    # col 0 lacks draw.USER_SENTINEL, or either cell is blank ("an unnamed column is a
    # rebuilt tab, not an unnamed boss" — trialSignup.js:100-102).
def cross_check(observed: GuildCombat, pair_labels: list[str]) -> str
    # "" when {norm_trial(h) for h in observed.hrids} == {norm_trial(l) for l in pair_labels};
    # else a reason naming BOTH sets and both possibilities (optimiser not yet run for this
    # week / sign-up tab not yet refreshed), without guessing which.
```

Verify: `.venv/bin/python -c "from src import combat; g=combat.parse_combat('', 'sc'); assert g.observed is False and g.tab=='SC Combat Teams'"`.

**Step 14 — `src/build.py`** ~35 min

1. Import: `from . import combat as combat_model` beside the `buildings_model` import.
2. `GuildSite.combat_tab` after `buildings_tab` (`:145-158`), before `out_dir` (`:160`):
   ```python
   @property
   def combat_tab(self) -> str:
       """This guild's machine-owned combat teams tab (config.COMBAT_TABS), written by the
       combat optimiser in ~/pie/SCLIRoster and read by src/combat.py. Read only when
       config.COMBAT_SOURCE_ENABLED is on. Starts empty; combat.parse_combat reports that
       as observed=False and trials.json says `available: false`."""
       return config.COMBAT_TABS[self.key]
   ```
3. `_GuildInputs`, after `buildings_unavailable` (`:4292`), before `plan_dict`:
   ```python
   # The optimiser's published combat teams (combat.GuildCombat), or None when not read.
   # Attached to trials.json by _write_guild as the `combat` key. Picklable dataclass.
   combat: Optional["combat_model.GuildCombat"] = None
   # Non-empty when the block is not usable: never written, unreadable, stale against the
   # sign-up header, or the flag is off. The text is what trials.json publishes verbatim.
   combat_unavailable: str = ""
   ```
4. New `_fetch_combat(site, signup_csv) -> tuple[Optional[GuildCombat], str]` immediately
   before `_fetch_guild` (`:4504`): the flag-off branch returns
   `(None, "config.COMBAT_SOURCE_ENABLED is off, so no combat teams are published.")`;
   the `try` calls `combat_model.scrape_combat_tab(site.combat_tab, site.key)` and, if
   observed, `combat_model.cross_check(obs, combat_model.signup_combat_pair(signup_csv, site.signup_tab))`;
   `except SheetStructureError as exc` → `(None, f"The {site.combat_tab!r} tab could not be read … Reason: {exc}")`;
   `observed=False` → `(obs, f"The {site.combat_tab!r} tab exists but has never been written — it fills the first time the optimiser runs `report --publish-combat`.")`;
   non-empty cross-check → `(obs, reason)`. Every non-empty reason is also printed as
   `WARNING ({site.key}): combat teams unavailable — {reason}` to stderr. `RuntimeError`
   propagates (the precedent, `:4593`).
5. In `_fetch_guild`: `signup_csv = ""` on its own line before `try:` at `:4647` (so the
   name is bound on every path — it already is where the fetch succeeded, but a reader
   should not have to prove that from the exception flow); then, after the
   `if unavailable: print(...)` block (`:4686-4690`):
   `combat, combat_unavailable = _fetch_combat(site, signup_csv)`; add both to the
   `_GuildInputs(...)` call (`:4693-4705`).
6. New `_combat_block(inputs, site) -> dict` before `_write_guild`, returning §4.2 exactly
   (`available` iff `inputs.combat is not None and inputs.combat.observed and not inputs.combat_unavailable`;
   `unavailable` defaults to `f"The {site.combat_tab!r} tab was not read."` when the reason
   is empty and the block is unavailable — reachable only from tests that build
   `_GuildInputs` by hand).
7. `_write_guild`, after `:4896` (the provenance block) and before the register projection:
   ```python
   # --- The optimiser's combat teams, on trials.json -------------------------------
   # After provenance and before the register projection, so `week` is complete before
   # anything projects from it. Gated: config.COMBAT_SOURCE_ENABLED = False is the
   # byte-for-byte rollback (no key). The block carries its own `available` /
   # `unavailable`, so a stale or missing tab is published as a stated absence rather
   # than a silent one — the userscript shows the reason.
   if config.COMBAT_SOURCE_ENABLED:
       week["combat"] = _combat_block(inputs, site)
   ```
8. `_summary_line`: beside `buildings_note` (`:4845-4850`)
   ```python
   if inputs.combat is not None and inputs.combat.observed and not inputs.combat_unavailable:
       combat_note = "combat " + inputs.combat.generated_at[:10] + " " + ", ".join(
           f"{combat_model.norm_trial(t.hrid)}x{len(t.roster)}" for t in inputs.combat.teams)
   else:
       combat_note = f"combat NONE — {inputs.combat_unavailable[:60]}"
   ```
   and `f"{combat_note}; "` before `f"signup: {signup_note}"` in the return (`:4852-4867`).

Verify: `.venv/bin/python -c "import src.build as b; s=b.GUILD_SITES[0]; assert s.combat_tab=='SC Combat Teams'; i=b._GuildInputs(site_key='sc',members=[],register={'member_count':0,'skills':[]},picks=None); blk=b._combat_block(i,s); assert blk['available'] is False and blk['trials']==[] and blk['source']=='SC Combat Teams'"`.

**Step 15 — tests** ~45 min

`tests/test_combat.py` (new, §8) and the three-line edit to
`tests/test_register_week.py:229-257`: first statement of the body
`monkeypatch.setattr(config, "COMBAT_SOURCE_ENABLED", False)` with the comment
"This test pins what the REGISTER projection does to trials.json (nothing but
provenance). The `combat` key is a different feature with its own on/off pin in
tests/test_combat.py, so it is switched off here rather than folded into the expectation."

Verify: `.venv/bin/python -m pytest tests/test_combat.py tests/test_register_week.py tests/test_roster.py -q`
→ all pass (the golden test untouched and green); then the full suite → 461 + 15 = 476 passed.

**Step 16 — `README.md`** ~10 min

New `### trials.json carries the combat teams` after `:535`: the key (§4.2 condensed), who
writes the tab, the cross-check, the degrade contract ("`available: false` is a statement,
not an error"), `COMBAT_SOURCE_ENABLED = False`, and one line to the SCLIRoster README.

**Step 17 — local build and the end-to-end assertion** ~10 min (+ ~4 min build)

```bash
cd /Users/morgan/pie/farm/guild && .venv/bin/python -m src.build 2>build.err; grep -n "combat" build.err
.venv/bin/python - <<'EOF'
import json
for d in ("_site", "_site/li"):
    w = json.load(open(f"{d}/trials.json")); c = w["combat"]
    assert set(c) == {"available", "unavailable", "source", "generated_at", "trials"}, d
    if c["available"]:
        assert len(c["trials"]) == 2 and all(t["hrid"].startswith("/guild_combat/") for t in c["trials"])
        assert all(t["party_size"] == len(t["roster"]) for t in c["trials"])
        assert all(set(r) == {"name", "role", "slot"} for t in c["trials"] for r in t["roster"])
    else:
        assert c["trials"] == [] and c["unavailable"], d
    print(d, c["available"], c["unavailable"][:80] or [f"{t['hrid']} x{t['party_size']}" for t in c["trials"]])
EOF
```
Expected today: SC `available: True` after step 11 (two hrids matching the SC sign-up
header's `Swarm, Badger` — **if** the optimiser's cycle agrees with the live sign-up header;
`data/guild.json` said chameleon/hedgehog on 2026-09-04 while the tab said Swarm/Badger,
so expect the STALE reason until the optimiser is run for the current pair); LI
`available: False` with "never been written" until step 11 is repeated for LI. Both are
correct outputs. Then commit (`feat(combat): trials.json carries the optimiser's combat
teams, read from a machine-owned tab`) with only this change's files.

### Layer 4 — the userscript glows both, and names the mismatch

**Step 18 — header and version** ~5 min

`:4` → `// @version      0.5.0`. `:38-46`: add the `combat` block to the shape sketch.
`:91-103`: the freshness note applies to `combatHrids` too. `:106-110`: replace "SKILLING
trials only…" with "BOTH disciplines since 0.5.0: the artefact's `combat` block carries the
optimiser's combat teams; the two combat tiles are keyed `trial_<boss>` (a different sprite
sheet per boss — key on the fragment, never the file). The member's OWN sign-up is read off
`guild_trial_signup_updated` / `guild_characters_updated` for the mismatch warning and for
nothing else."

Verify: `node -e 'const m=require("fs").readFileSync("scli-roster.user.js","utf8").match(/@version\s+(\S+)/);console.log(m[1])'` → `0.5.0`.

**Step 19 — state, ingest, the sign-up reads** ~25 min

- `state` (`:530-566`): `weekStartAt: null` (the game's `guild.currentWeekStartAt`),
  `combatDrawHrids: null` (Set of hrids from `guildWeeklyTrialSet.combatHrids`),
  `combatAssignment: null` (`{ hrid, slug, team, partySize, role, slot }`),
  `combatStatus: "starting"`, `combatProblem: null`,
  `signup: null` (`{ skillingHrid, combatHrid, weekStartAt, source: "event"|"roster", at }`).
- `ingest()`: inside the `p.guild` block (`:667-693`) read
  `if (typeof p.guild.currentWeekStartAt === "string") state.weekStartAt = p.guild.currentWeekStartAt;`
  (every time, like the notice); in the guild-change branch (`:672-678`) also
  `state.combatAssignment = null; state.signup = null;`. Beside the `skillHrids` read
  (`:694-702`): `if (wts && Array.isArray(wts.combatHrids)) { const h = new Set(wts.combatHrids.map(String)); if (h.size) state.combatDrawHrids = h; }`.
  Then the cold-load sign-up read — `guild_characters_updated` already reaches `ingest`
  (`:3293`):
  ```js
  // My own sign-up, from the whole-roster message the Members panel triggers. The
  // record's key is `characterID` (capital D) — the flat sign-up EVENT uses
  // `characterId`. Both spellings are real; naming one would silently miss a path.
  const gcm = p.guildCharacterMap;
  if (gcm && typeof gcm === "object" && state.characterId) {
      const rec = gcm[String(state.characterId)]
          || Object.values(gcm).find((r) => r && String(r.characterID) === String(state.characterId));
      if (rec) recordSignup(rec, "roster");
  }
  ```
- New `ingestSignup(msg)` (its own handler, per `:3295-3297`): `p.characterId` must equal
  `state.characterId` (string compare) or return; else `recordSignup(p, "event")`.
- `recordSignup(rec, source)` sets `state.signup = { skillingHrid: rec.signedUpSkillingTrialHrid || "", combatHrid: rec.signedUpCombatTrialHrid || "", weekStartAt: rec.signupWeekStartAt || null, source, at: Date.now() }` and calls `recompute()`.
- `maybeRefresh` no-url branch (`:762`): `state.combatAssignment = null;` beside `state.assignment = null;`.
- Registration after `:3293`: `onWs("guild_trial_signup_updated", ingestSignup);`.

Verify: `node --check scli-roster.user.js`; `npm test` still green for `test/userscript.test.js`.

**Step 20 — `recomputeCombat`, `combatTileSlug`, `signupVerdict`** ~30 min

```js
// "/guild_combat/chameleon" -> "trialchameleon": what BOTH of slugOfTile's paths yield
// for that tile (fragment "trial_chameleon", label "Trial Chameleon"). Keyed on the
// hrid, the game's own identifier, which is also what combatHrids and
// signedUpCombatTrialHrid carry — so freshness and mismatch compare hrids directly.
function combatTileSlug(hrid) {
    const boss = normSkill(String(hrid || "").split("/").pop());
    return boss ? "trial" + boss : null;
}

// One of: "unknown" (no sign-up seen yet) | "stale" (a previous week's) | "none"
// (signed up for nothing) | "agree" | "mismatch". Unknown is NOT agreement.
function signupVerdict(signedHrid, assignedHrid) {
    if (!state.signup) return "unknown";
    if (!state.weekStartAt || state.signup.weekStartAt !== state.weekStartAt) return "stale";
    if (!signedHrid) return "none";
    if (!assignedHrid) return "none";           // signed up, nothing assigned: informational
    return signedHrid === assignedHrid ? "agree" : "mismatch";
}
```
`recompute()` (`:794-857`): `state.combatAssignment = null; state.combatProblem = null;` at
the top; and `recomputeCombat(art, me)` inserted after the skilling lookup (`:838-848`) and
before `state.status = …` (`:850`) — i.e. only once the skilling set guard has passed (an
artefact that predates the draw rotation predates the combat block too).
`recomputeCombat`: absent key → `combatStatus = "this artefact carries no combat data"`;
`available === false` → `combatStatus = "no combat data — " + unavailable`; hrid set ≠
`state.combatDrawHrids` (when known) → `combatProblem` in the wording of `:828-831`; else
find `me` in `trials[].roster[].name` via `normName` → `combatAssignment`. For the
skilling side, `assignedHrid` is `"/guild_skilling/" + state.assignment.slug` (the game's
skilling hrids use the sprite slugs — `ingest` already splits them at `:696`).

Verify: step 23's tests.

**Step 21 — `decorate()` and the CSS** ~25 min

`decorate()` (`:2078-2100`) computes a `wants` Map (slug → `{ kind, title }`) from the
skilling and combat assignments (each only when its own `problem` is null) and a `picked`
Set of slugs the member SIGNED UP for that differ from their assignment in the same
discipline (only when the verdict is `mismatch`). Per tile: `scli-assigned` iff in `wants`,
`scli-mismatch` iff in `picked`; both toggles short-circuit when already right (the `!!`
note at `:2084-2088` applies to both). Ribbon text: `"Your assigned trial"` / `"Your sign-up
— NOT your assignment"`. Title: `"SC/LI Roster: you are on the Trial Chameleon team (SC Team 1, 16 members)."`.
CSS after `:2308`: `.scli-mismatch` — an amber ring (`rgba(255,140,0,…)`), no pulse, its
own `::after` ribbon, and the same `prefers-reduced-motion` guard. Distinct from the gold
glow AND from the game's own `GuildPanel_trialTileMine` styling, which it may sit on top of.

Verify: `node --check`; the decorate test in step 23.

**Step 22 — the panel** ~20 min

`buildPanel` rows (`:2713-2718`): add `["combat", "Combat trial"]`, `["signup", "Sign-up check"]`;
a second verdict line `els.combatVerdict` under `els.verdict`. `paint()` (`:2966-2988`):
combat verdict `★ Combat: Trial Chameleon (SC Team 1)` / warn / none; `rows.combat` = boss
and team; `rows.signup` = `skilling: <verdict text> · combat: <verdict text>` where the texts
are: unknown → "not yet known — open Guild ▸ Members"; stale → "your last sign-up was for a
previous week"; none → "none"; agree → "matches"; mismatch → "MISMATCH: signed up <X>,
assigned <Y>". When either is `mismatch`, `els.note` shows the sentence and the verdict
takes `is-warn`. `dump()` (`:3316-3339`) gains `weekStartAt, combatDraw, combatAssignment,
combatStatus, combatProblem, signup, verdicts`. `Ui` (`:3361`) gains `combatTileSlug, signupVerdict`.

Verify: `node --check`; `npm test`.

**Step 23 — `test/combat.test.js` (new)** ~40 min

See §8. Verify: `npm test` → 958 + 14 + (19 − 14 apps-script; those are farm/guild's, not
counted here) … concretely: `node --test test/combat.test.js` → 14 pass; `npm test` → the
previous count + 14 + the optimiser's new tests, 1 pre-existing failure.

**Step 24 — live check in the game (manual; the n=2 sprite fact demands it)** ~15 min

Install the local file in Tampermonkey, load the game on a character in SC, open
Guild ▸ Trials. In the console: `SCLIRoster.dump()` → `combatDraw` has two hrids,
`combatAssignment.slug` is `trial<boss>`, and the corresponding tile carries
`scli-assigned`. Open Guild ▸ Members → `dump().signup.source === "roster"` and
`verdicts` no longer `unknown`. Change a sign-up and back → `signup.source === "event"`.
If the character is assigned and signed up differently, the amber ring sits on the
sign-up tile and the panel names both. Check on a second character in LI (multi-character
reality: the switch must extinguish SC's glow, `:672-678`).

**Step 25 — publish** ~5 min

`npm run release` (`scripts/publish.sh`): the tests gate, then the `@version` gate (`:58-78`)
passes because 0.5.0 > 0.4.1. Close `todo.md:386-396`.

**Total: ~9 h** of implementation across the four layers (L1 ≈ 1 h incl. deploy, L2 ≈ 2.5 h,
L3 ≈ 2.7 h, L4 ≈ 2.7 h) plus one farm/guild build (~4 min) and a game session, plus 20 %.

## 8. Test plan

### `apps-script/Code.test.js` (14 → 19)
| test | pins |
|---|---|
| `a combat block is written to its own tab, with Guild Id as a real number and everything else text` | `format === "combat"`, `columns === 7`, A1 `Member`, `typeof _grid[1][5] === "number"`, hrid text preserved |
| `the combat block goes to either guild's tab, independently` | LI write leaves SC's tab at `getLastRow() === 0` |
| `a COMBAT block sent to a SIGN-UP tab is refused, and the roster survives` | `/format mismatch/`, `/combat block/`, grid byte-identical |
| `a SIGN-UP block sent to a COMBAT tab is refused, and the teams survive` | mirror |
| `a BUILDINGS block sent to a COMBAT tab is refused` | the interlock is three-way, not two |
| *(edit)* `a header naming neither format is refused…` `:217` | the new three-way message |
| *(edit)* `doGet lists exactly the seven real tabs, with their formats` `:276-294` | 7 tabs, the map |

### `optimizer/test/combat-tab.test.js` (new) + `credentials.test.js` (+2)
| test | pins |
|---|---|
| `HEADER is the seven-cell contract, verbatim` | the literal array — the cross-repo contract |
| `TAB_BY_GUILD names the two machine-owned tabs and nothing else` | exactly `sc`/`li` |
| `the two tab names appear in farm/guild's Code.gs TAB_FORMAT as 'combat'` | reads `/Users/morgan/pie/farm/guild/apps-script/Code.gs` when present (skips with a note when absent, as the csim boundary tests do) |
| `rows: one per named seat, seven cells, sorted team then slot` | fixture `assignResult` with 5 assignments across two teams |
| `a seat with no current name is listed in unnamed and NOT written` | never guessed |
| `no characterId reaches a row` | `JSON.stringify(rows)` contains no fixture id and no `characterId` |
| `a non-combat trialHrid is refused by name` | `/guild_skilling/…` throws |
| `publishTargetFor refuses an unknown guild` | throws naming the two tabs |
| `postCombatTab sends exactly {secret, tab, header, rows} as JSON` | fake `fetchImpl` captures the body |
| `ok:false is a refusal with the fix spelled out, and the secret is never in the message` | `unauthorised` → "secret"; `tab not found` → "create it"; `format mismatch`; `redact` asserted |
| `HTML and non-2xx are refusals, not data` | mirrors `credentials.test.js:224-257` |
| `a timeout is reported with its budget` | mirrors `:284` |
| `loadCombatWriteCredentials names the missing keys` / `…refuses a non-/exec URL and does not echo it` | in `credentials.test.js` |
| `the only module that POSTs to script.google.com is publish/combatTab.js` | grep over `optimizer/src/**/*.js` for `script.google.com` + `method: 'POST'` — the R4 pin, in the manner of `blast-radius.test.js:33-40` |

### `tests/test_combat.py` (new, 15) and one existing edit
| test | pins |
|---|---|
| `test_parses_a_machine_written_tab` | fixture of 5 rows / 2 teams: `observed`, `generated_at`, teams in first-seen order, `party_size`, `to_dict()` == §4.2 shape |
| `test_empty_tab_is_unobserved_not_an_error` | `""`, `"\n"`, header-only → `observed False`, `tab` filled from config |
| `test_a_wrong_tab_serve_raises` | the `WRONG_TAB_CSV` shape from `test_buildings.py:56-61` → `SheetStructureError` naming col 0 |
| `test_a_changed_writer_header_raises` | one header cell renamed |
| `test_another_guilds_id_raises` | `Guild Id` 240 on the `sc` tab |
| `test_a_non_combat_hrid_raises` | `/guild_skilling/milking` in Trial Hrid |
| `test_a_blank_member_name_raises` | machine tab; a blank name is a broken write |
| `test_signup_combat_pair_reads_cells_five_and_six` | today's SC header → `["Swarm", "Badger"]`; a 5-cell header raises; a blank cell raises |
| `test_cross_check_is_order_case_and_form_insensitive` | `{/guild_combat/swarm, /guild_combat/badger}` vs `["Badger", "Swarm"]` → `""`; vs `["Chameleon", "Hedgehog"]` → reason names both sets |
| `test_fetch_combat_degrades_on_every_non_network_failure` | monkeypatch `combat_model.scrape_combat_tab`: raises `SheetStructureError` → `(None, "could not be read…")`; unobserved → `(obs, "never been written…")`; stale → `(obs, "…lists…")`; good → `(obs, "")`; each prints a `WARNING` (capsys) except the last |
| `test_fetch_combat_lets_a_network_error_propagate` | `RuntimeError` → `pytest.raises` (the precedent, stated) |
| `test_flag_off_skips_the_fetch_entirely` | `COMBAT_SOURCE_ENABLED=False` → scrape never called (monkeypatch counter), reason names the flag |
| `test_write_guild_attaches_the_block_on_both_guilds` | `tmp_path`, `OUTPUT_DIR` monkeypatched; `_inputs(...)` with a `GuildCombat` → `published["combat"]["available"] is True` and `trials` as given; with `combat=None` → `available False` and the default reason; the summary string contains `combat` |
| `test_flag_off_is_byte_identical_and_on_is_additive` | modelled on `test_register_week.py:260-294`: `set(on) - set(off) == {"combat"}`; every other key equal after popping `generated_at`/`week_date` (`test_roster.py:388-389`) |
| `test_shipped_flag_is_on` | `config.COMBAT_SOURCE_ENABLED is True` — the `test_trials.py:1235-1250` pattern, in this module |
| *(edit)* `tests/test_register_week.py::test_write_guild_publishes_the_week_on_both_guilds_and_leaves_trials_json_alone` | flag pinned off; `:250` unchanged in text |

### `test/combat.test.js` (userscript, new, 14) — all through `harness.load()`
The harness's `location.search` is `?characterId=17` (`harness.js:112`), the artefact
fetch 404s (`:137-143`), and `api.state`, `api.recompute`, `api.decorate` are exposed
(`scli-roster.user.js:3311-3316`), so tests set `api.state.artefact` directly and drive
frames with `deliver()`.

| test | pins |
|---|---|
| `combatTileSlug agrees with both of slugOfTile's paths` | `Ui.combatTileSlug("/guild_combat/chameleon") === normSkill("trial_chameleon") === normSkill("Trial Chameleon") === "trialchameleon"` |
| `init_character_data yields the combat draw and the week start` | `dump().combatDraw` two hrids; `weekStartAt` |
| `a current combat block names my team and tile` | `combatAssignment.slug === "trialchameleon"`, `team`, `partySize` |
| `a combat block for a different pair glows nothing and says so; skilling is untouched` | `combatProblem` set, `assignment` intact |
| `an artefact without the key is not an error` | `combatStatus` says so, nothing thrown |
| `available:false carries the reason into the panel state` | `combatStatus` contains the reason |
| `guild_trial_signup_updated for ME is recorded; for another id ignored` | `characterId` 17 vs 99 |
| `guild_characters_updated records my sign-up through characterID` | map key `"17"`, record `characterID: 17` — the casing path |
| `unknown is not agreement` | no sign-up frame → both verdicts `unknown` |
| `a previous week's sign-up is stale, never a mismatch` | `signupWeekStartAt` ≠ `currentWeekStartAt` |
| `a mismatch is named in both disciplines` | swarm signed / chameleon assigned; alchemy signed / enhancing assigned |
| `decorate glows the assigned tiles and rings the mismatched sign-up, idempotently` | `sandbox.document.querySelectorAll = () => tiles` with hand-built tiles (fragment hrefs from the capture); `scli-assigned` on two, `scli-mismatch` on one, none on both; a second call changes nothing |
| `a guild change clears the combat assignment and the sign-up` | `guild_updated` with a new id |
| `phase 1 still works, and a throw in the combat path cannot break it` | mirrors `userscript.test.js:631` with a malformed `combat` value (`"combat": 42`) |

## 9. Risks

**R1 — an officer, or a stray hand, edits a machine-owned tab.** *Probability medium
(the tab sits beside hand-maintained ones), impact low.* The header guard is equals on all
seven cells, the guild id and hrid prefix are checked per row, and a blank name raises —
any edit that changes shape yields `available: false` with the guard text, a CI
`WARNING`, and the panel showing the reason; an edit that keeps shape (a retyped name) is
overwritten by the next `--publish-combat`, which clears and rewrites from A1
(`Code.gs:164-172`). `apps-script/README.md` names both tab pairs as machine-owned.
*Detection:* the CI summary's `combat NONE — …` clause. *Contingency:* re-run the publish.

**R2 — the optimiser and the site disagree about the week.** *Probability medium every
Friday, impact high if unguarded.* Two independent set comparisons, no date comparison
anywhere: the build cross-checks the tab's two hrids against the guild's own sign-up
header (cells 5–6), withholding the block and naming both sets when they differ; the script
compares the block's hrids against `guildWeeklyTrialSet.combatHrids` and glows nothing on a
mismatch. The `cycle` id, `week_date`, `Generated At`, `signupWeekStartAt` and
`currentWeekStartAt` are never compared with one another; the only week comparison in the
script is game-string to game-string (`signupWeekStartAt === guild.currentWeekStartAt`).
*Detection:* the stale reason in `trials.json` and the CI line. *Contingency:* wait — it
resolves itself when the lagging side catches up, as the skilling withhold does.

**R3 — a rebuilt sheet (tab deleted, renamed, reordered).** *Probability low, impact
low.* gviz serves the first tab for an unknown name → the header guard fails → degrade,
with the message saying the tab may not exist. The write side cannot follow a rename:
`doPost` refuses any tab not in `TAB_FORMAT` and never creates one (`Code.gs:113-115`,
`:143-146`), and the CLI prints `tab not found: "SC Combat Teams" — create it first`.
*Detection:* the CLI refusal and the CI `WARNING`. *Contingency:* recreate the tab by its
exact name; nothing else moves.

**R4 — a later author widens the write path further.** *Probability medium over a year,
impact high.* Three interlocks and three statements: `publishTargetFor` throws for any tab
outside `TAB_BY_GUILD`; farm/guild's `TAB_FORMAT` refuses a `combat` block on any other tab
and any other block on these; the private sheet has no URL in `publish/` (a test greps
`optimizer/src` for POSTs to `script.google.com` and requires the only hit to be
`publish/combatTab.js`); and the narrowed invariant is written where the old one was
(`pins-writeback.test.js`, `plan-implementation.md` ×2, `render.js`) plus the module
banner, so the next reader meets the rule before the mechanism. *Detection:* the grep test.

**R5 — the glow is confused with the game's own `GuildPanel_trialTileMine` marker.**
*Probability high (both sit on the same grid), impact medium (a member acts on the wrong
one).* The gold glow means "assigned by the optimiser" and carries the ribbon "Your
assigned trial"; the amber ring means "your sign-up, NOT your assignment" and appears only
on a mismatch; the panel's Sign-up row spells out both hrids; and the tile `title` says
which is which. Neither uses the game's class or its styling. *Detection:* step 24's live
check on a mismatched character. *Contingency:* the wording is text in one place each;
adjust and republish.

**R6 — unknown read as agreement.** *Probability high on every cold load, impact
medium.* `signupVerdict` has a first-class `unknown` and a first-class `stale`; both are
tested; the panel says "open Guild ▸ Members" for the first. A page that has seen no
sign-up frame never says "matches".

**R7 — a combat parse failure stops the deploy (the 2026-07-25 class).** *Probability
low, impact catastrophic.* `_fetch_combat` catches `SheetStructureError` on every path;
`parse_combat` raises only that class for sheet content; the attach is field access on a
dataclass; the flag skips the fetch entirely. Network `RuntimeError` propagates by the same
rule as every other tab (`build.py:4552`, `:4593`, `:4645`) — the member tab on the same
host would have failed first. Pinned by `test_fetch_combat_degrades_on_every_non_network_failure`.

**R8 — the name join misses.** *Probability low-medium (`Yiyaa`/`yiyya`-class names,
renames), impact low.* The optimiser writes `names.current` (the roster harvest's in-game
name at capture); the script folds case and whitespace (`normName`, `:315-317`), as it
already does for skilling. A miss yields "no combat assignment" — never a wrong glow. Seats
with no current name are refused and counted by the CLI.

**R9 — the secret leaks.** *Probability low, impact medium (a stranger can POST junk to
an allowlisted tab — and only to one; the interlock caps the blast radius at the machine
tabs).* The secret lives only in `~/.config/scliroster/credentials.json` (outside both
trees by construction, 0600, `credentials.js:65-91`); every error passes `redact()`; the
tree keeps the placeholder; the preview file carries no secret. *Contingency:* rotate in the
Apps Script editor and the credentials file — two places, as `apps-script/README.md:119-121`
says today.

**R10 — the PII gate is weakened.** *Probability low, impact high to trust.* Names go to
the public sheet's machine tab, where `SC Trial Signup` already lists every member;
`characterId` never enters a row (tested); the `.md`/`.json` report redaction is unchanged;
the preview file is scanned for the id half exactly as the dashboard is (`cli.js:1788`).

**R11 — the casing trap.** *Probability high for a naive edit, impact medium (a silent
miss of the cold-load path).* Both spellings are used, in the same lines, with the comment;
two tests exercise the two paths separately.

**R12 — the dirty trees.** *Probability certain, impact low.* SCLIRoster's one failing test
is unrelated and stays failing until its comment edit is committed; farm/guild's uncommitted
buildings/register work is the substrate this plan builds on. Stage only this change's files
per commit; `git add -p` on the four shared files.

**If implementation gets stuck:** each layer ships alone. L1 alone is an allowlist entry
nobody uses; L1+L2 fill a tab nobody reads; L1–L3 publish a key nobody consumes (the script
ignores it); L4 without L3 says "this artefact carries no combat data". Stop at any layer
boundary and the site is correct.

## 10. Rollback — per layer, and what `False` restores

**Layer 3 (the one-line rollback):** `COMBAT_SOURCE_ENABLED = False` in `src/config.py`,
push to `main`. No fetch is made and `trials.json` regains exactly today's key set and
content (pinned by `test_flag_off_is_byte_identical_and_on_is_additive`). The userscript
then reports "this artefact carries no combat data" and glows skilling as before. ~30 s to
edit; one CI run. **Full:** `git revert <the L3 commit>` or `git reset --hard 086de16`
before push; confirm `.venv/bin/python -m pytest tests/ -q` → 461 passed and
`python3 -c "import json; assert 'combat' not in json.load(open('_site/trials.json'))"`
after a rebuild.

**Layer 4:** members on 0.5.0 keep working against an artefact without the key (§5). To
withdraw the script itself, revert the code AND bump `@version` to `0.5.1` — `publish.sh`
refuses a version that does not go up (`:58-78`), so a rollback is a forward release with
the old code. `git revert <the L4 commit>` locally, then edit `:4`, then `npm run release`.

**Layer 2:** stop passing `--publish-combat`; the tab keeps its last content, which L3
will report as stale once the sign-up pair moves on (a correct statement). To blank the tab,
clear it in the sheet UI. To remove the path: `git revert <the L2 commit>`; delete the two
keys from `~/.config/scliroster/credentials.json`; `npm test` back to the baseline count.

**Layer 1:** remove the two `TAB_FORMAT` entries and the `formatOf_` line, redeploy a new
version (`apps-script/README.md:108-112`) — or simply delete the two tabs: `doPost`
refuses a missing tab and never creates one. `node --test apps-script/Code.test.js` → 14
after reverting the test file.

**Order:** any single layer may be rolled back alone (§5 is the proof); the full unwind is
L4 → L3 → L2 → L1, each independently verifiable by the command beside it.

**Triggers:** any `combat NONE — could not be read` on two consecutive live builds
(something changed the tab's shape); a member report of a glow on a tile they are not
assigned to (would be R2 or R5); the CLI refusing a publish with `format mismatch` (the tab
map has drifted); any red in either suite.

## 11. Success criteria

- `SC Combat Teams` and `LI Combat Teams` exist, are written by `report --publish-combat`
  in the seven-column §4.1 layout, and `Code.test.js` passes at 19 with the three-way
  interlock pinned.
- `optimizer/test/combat-tab.test.js` passes; the invariant is amended in all four places
  and the grep test proves `publish/combatTab.js` is the only POST to `script.google.com`.
- `_site/trials.json` and `_site/li/trials.json` carry `combat` in the §4.2 shape; on live
  data SC reads `available: true` once the optimiser has published this cycle's pair, and
  every degraded state in §5 yields `available: false` with a non-empty reason and a CI
  `WARNING`, never a failed build.
- `tests/test_combat.py` passes; `tests/test_register_week.py` passes with one three-line
  edit; `tests/test_roster.py`'s golden is untouched and green; the full suite is 476.
- `COMBAT_SOURCE_ENABLED = False` reproduces today's `trials.json` byte-for-byte.
- In the game, on a character with both assignments: two gold tiles; on a character whose
  sign-up differs: an amber ring on the sign-up tile and the panel naming both; on a cold
  load: "sign-up not yet known"; after a character switch: nothing from the previous guild.
- `test/combat.test.js` passes; `@version` is `0.5.0`; `scripts/publish.sh` accepted it.
- No file in `src/trials.py`, `src/signup.py`, `src/draw.py`, `_attach_week`,
  `_provenance_block`, `.github/workflows/`, `scripts/publish.sh`, or SCLIRoster's
  `apps-script/` changed.
- Every non-obvious choice carries its reasoning in a comment where the code is: the hrid
  key, the two `characterId` spellings, the unknown ≠ agree rule, the game-to-game week
  comparison, the no-provenance decision, the narrowed invariant.

Quality checklist: no signature changed · APIs match the source cited (no invented
functions — every helper named above is new and defined here, every existing one is cited)
· additive JSON only · secrets outside both trees · names but no ids leave the optimiser ·
one flag, one rollback line · only this change's files staged.

## 12. Metadata

- Created 2026-09-09 against farm/guild `086de16` (dirty tree as described) and SCLIRoster
  `fab85ab` (dirty tree as described); anchors are working-tree line numbers.
- Agent: implementation-planner. DeepWiki: not applicable (no external library; Node 25.2.1
  for `globalThis.fetch`, `AbortController`; Python per `.venv`).
- Complexity: medium-high (four layers, two repositories, one manual deploy, one manual
  game check); each layer individually low.
- Risk: medium — the write path is new in kind, and is fenced by an allowlist interlock that
  is one commit old and tested; everything on the read side degrades by construction.
