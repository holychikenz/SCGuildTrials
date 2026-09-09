# Implementation plan — read guild building levels from the `SC Buildings` / `LI Buildings` tabs

**ResearchPack:** none — no external library is involved. The research is (a) the
codebase, every API cited `file:line` against the working tree at `842faeb`, and (b) the
**live sheet**, fetched during planning. **Baseline:** `.venv/bin/python -m pytest
tests/test_trials.py tests/test_scraper.py tests/test_reader.py -q` → **168 passed in
57s**. **Precedent:** `src/scraper.py` for the guarded gviz read, `trials.community_buff_level`
(`trials.py:180-227`) for the injection, `_unit_jobs`' `shrine_caps` (`build.py:4893-4897`)
for the parent-resolves/child-receives contract.

---

## 1. What changes, in one paragraph

`config.GUILD_BUILDING_LEVELS` (`config.py:1557-1568`) is a hand-maintained map of ten
zeros, shared by both guilds, and its own comment says to split it per guild "the moment
real levels arrive". They have arrived: the Tampermonkey module and the Apps Script
endpoint the user has just built write each guild's 23 building and 5 shrine levels to a
per-guild tab. After this change the build **reads** those levels — one guarded gviz fetch
per guild in the parent, resolved to trial-skill levels, shipped with each optimiser job,
and bound around `run_week` for the duration of that guild's unit. The shipped config map
stays all-zero and becomes the *fallback*, so the golden week stays bit-identical and
`config.BUILDINGS_SOURCE_ENABLED = False` restores today's behaviour exactly.

**This will move the model.** SC's Guild Observatory is at level 1, so Enhancing gains
`+2` skill levels guild-wide in the success calc; the other nine skilling buildings are
unbuilt. LI's tab is empty, so LI is unchanged. That single `+2` is the entire behavioural
delta, and §7 requires it be eyeballed rather than assumed.

## 2. The facts this plan rests on (all verified)

| Claim | What the source actually says |
|---|---|
| The tabs exist and are populated | Fetched live 2026-09-09. `SC Buildings` returns a clean single header row `"Building","Hrid","Kind","Level","Guild Id","Captured At"` and **28 data rows** (23 `building` + 5 `shrine`), `Guild Id` = 4, `Captured At` = `2026-09-09T13:00:53.934Z` on every row. |
| `LI Buildings` exists but is **empty** | `HTTP 200`, **0 bytes**. Distinguished from a missing tab by experiment: a deliberately bogus tab name (`ZZ Nonexistent Tab`) returns **3518 bytes of the first tab's content** — the silent wrong-tab serve `scraper.py`'s docstring warns about. So `0 bytes` ⇒ tab exists, never written; junk header ⇒ wrong tab. The parser must treat these as **different outcomes**. |
| The writer's contract | `apps-script/README.md:25-36, 44-54`: header is exactly those six cells, 28 rows, tabs are created **by hand and empty**, "the first write fills them"; `TAB_FORMAT` refuses a levels block on a sign-up tab and vice versa. `apps-script/Code.test.js:123-124` shows shrine rows in the same block. |
| Guild ids | `apps-script/Code.gs:79` — Survey Corps 4, Lactose lntolerance 240. There is **no** guild-id map in Python today (`grep guild_id src/*.py` → nothing; the roster tab has a `guildId` column that nothing reads). §4.1 adds one, because the `Guild Id` column is a free cross-check that the right tab reached the right guild. |
| `GUILD_BUILDING_LEVELS` has exactly **one** read site | `trials.py:403` inside `guild_building_skill_levels(skill)` (`:399-404`), which clamps to `0..GUILD_BUILDING_MAX_LEVEL`. Ten callers reach it (`trials.py:777, 1021, 1143, 1227, 1590`; `optimizer.py:352`; `calibrate.py:1034, 1185, 1543`; `simulate_trial.py:114`) and **every one reads the global at call time**. `build.py:2900` names the constant in page prose; `build.py:1754-1772` renders from `week["guild_building_levels"]`, not from config. |
| The `WeekResult` records the levels it actually ran under | `trials.py:2632-2634`: `guild_building_levels={skill: guild_building_skill_levels(skill) for skill in skills}`. So an injection made around `run_week` is captured in the JSON and rendered by the footnote with no further plumbing. |
| The child is a real process | `_compute_unit` (`build.py:4554`) is "the child-process entry point … pickles by reference under both `fork` and `spawn`", run through `ProcessPoolExecutor` (`:4917-4922`) — with an in-process sequential fallback when `BUILD_PARALLEL` is off or there is one job (`:4907-4909`). Both paths matter to §5.3. |
| The parent already resolves per-guild scalars and ships them | `_unit_jobs`' `common` dict carries `cap` and `shrine_caps` with the comment "resolved here in the parent and shipped with the job rather than looked up in the child: the unit is plain data by contract, and a child re-deriving it from a key would be a second place for the mapping to be read" (`build.py:4890-4897`). `GuildSite.party_cap` / `.shrine_caps` (`build.py:123-142`) are the property idiom. |
| A degraded second-source read must not fail the deploy | `_fetch_guild`'s roster block (`build.py:4440-4459`) catches `SheetStructureError`, warns to stderr, records a reason, and ships from the fallback — explicitly because "SC is `required=True`, so an uncaught raise here would take down every page of BOTH guilds". A network `RuntimeError` still propagates. |
| The golden week must stay bit-identical | `tests/test_roster.py:363-403` compares `run_week(...)` output with `==`, not `approx`, against a golden generated at commit `265326b`. It calls `run_week` **bare**, entering no injection scope, so it reads the shipped config default. Keeping that default at zeros is what makes this change invisible to it. |
| Fifteen existing tests drive the feature by patching the dict | `tests/test_trials.py:206, 211, 219, 227, 232, 244, 256, 268, 286, 309, 415, 433, 473, 850` all use `monkeypatch.setitem(config.GUILD_BUILDING_LEVELS, …)`. Any design that replaces the global with a threaded parameter rewrites all fifteen. |
| Staleness has an established idiom | `ROSTER_MAX_AGE_DAYS = 14` (`config.py:301-307`) — "A BANNER THRESHOLD, NOT A CUTOFF: an old capture is still better data than the assumption it replaces, and refusing it would silently restore the assumption." Used at `build.py:262, 359, 429`. |

## 3. The one design decision, argued

**Bind `config.GUILD_BUILDING_LEVELS` in a restoring scope around each guild's unit.
Do not thread a `building_levels` parameter.**

The rejected alternative is what `config.py:1553-1556` itself proposes: thread a guild key
"through `trials.run_week` -> `simulate_race`/`optimize` -> `rate`". Against it:

1. **Ten call sites in four modules**, all of which read the global at call time
   (§2). A parameter must reach every one, including the optimiser's hot loop
   (`optimizer.py:352`) and two calibration harnesses that are not part of the build at all.
2. **Fifteen tests** currently express the feature by patching the dict (§2). Threading
   rewrites them, which converts a data change into a test-suite rewrite and destroys the
   review property that the diff is small.
3. **The repo has already made this exact call, in writing.**
   `trials.community_buff_level` (`trials.py:180-201`) rebinds five config globals for a
   scope and argues the case: "*Rebinding module constants rather than threading a `level`
   parameter is deliberate … the buffs are common-mode across the whole party by
   definition, and a parameter would have to be carried through `member_bonuses` ->
   `_prepare_member` -> `rate` -> `simulate_race` -> the optimizer's hot loop.*" Guild
   building levels are common-mode across the whole *guild* by definition — a strictly
   stronger claim than the one that argument was accepted for. `_compute_unit` already runs
   inside that context manager (`build.py:4599`).
4. **Thread-safety, the stated caveat of that idiom, is satisfied here for the same
   reason.** `community_buff_level`'s docstring says it is "NOT thread-safe, and not
   intended to be … which is why this must be a process of its own rather than a thread"
   (`build.py:4560-4563`). The new scope lives in the same function, under the same
   guarantee. The sequential fallback (`build.py:4908`) is safe because the scope restores
   on the way out, exception or no — and §5.3 makes that a test rather than a hope.

The cost of the decision is honest and bounded: `config.GUILD_BUILDING_LEVELS` becomes a
*fallback default* whose live value is injected by the caller, and it must be documented as
such in exactly one place (`config.py`) so the next reader is not misled by a map of zeros.
The benefit is that the config-shaped rollback survives, the golden stays green untouched,
and the diff outside the new module is ~40 lines.

## 4. File changes

### 4.1 `src/config.py` — additive, plus one comment rewrite

Append a `--- Guild buildings: the live source ---` block immediately after
`GUILD_BUILDING_POINT_COSTS` (`:1594-1599`):

```python
BUILDINGS_SOURCE_ENABLED = True      # False -> the build never fetches the tab and
                                     # every guild runs on GUILD_BUILDING_LEVELS,
                                     # bit-for-bit as before. The one-line rollback.
BUILDING_TABS = {"sc": "SC Buildings", "li": "LI Buildings"}
GUILD_IDS = {"sc": 4, "li": 240}     # apps-script/Code.gs:79
BUILDINGS_SENTINEL_HEADERS = {       # 0-based col -> ("equals", expected)
    0: ("equals", "Building"), 1: ("equals", "Hrid"), 2: ("equals", "Kind"),
    3: ("equals", "Level"), 4: ("equals", "Guild Id"), 5: ("equals", "Captured At"),
}
BUILDING_HRID_TO_SKILL = {           # the ten SKILLING buildings only
    "/guild_buildings/dairy_barn": "Milking",
    "/guild_buildings/garden": "Foraging",
    "/guild_buildings/log_shed": "Woodcutting",
    "/guild_buildings/forge": "C.Smithing",
    "/guild_buildings/workshop": "Crafting",
    "/guild_buildings/sewing_parlor": "Tailoring",
    "/guild_buildings/kitchen": "Cooking",
    "/guild_buildings/brewery": "Brewing",
    "/guild_buildings/laboratory": "Alchemy",
    "/guild_buildings/observatory": "Enhancing",
}
```

`BUILDING_HRID_TO_SKILL` is a *transcription* of the hrid→skill list already written in
prose at `config.py:1528-1535`; the plan puts it in a dict and the comment there gains a
one-line pointer so the two cannot drift. The seven combat buildings, the two encampments
and the four utility buildings are deliberately **absent** — they grant no skilling level,
and an hrid this map does not name is ignored (counted, §4.2).

Rewrite the `CURRENT DATA (guild_updated capture 2026-07-22 …)` paragraph
(`config.py:1541-1556`), whose "SPLIT THIS PER GUILD the moment real levels arrive"
instruction this change discharges. It must now say: these values are the **fallback**, used
when `BUILDINGS_SOURCE_ENABLED` is off or a guild's tab is unreadable/unwritten; the live
values come from `BUILDING_TABS` via `src/buildings.py`; and all-zero is retained on purpose
because it is what keeps `tests/test_roster.py::test_roster_disabled_reproduces_the_golden_week`
bit-identical.

No `ROSTER_MAX_AGE_DAYS` twin is added. The buildings read reuses it, with a one-line note:
building levels change far more slowly than a member's levels, so a threshold tuned for the
roster is conservative here, and a second constant is a second thing to drift.

### 4.2 `src/buildings.py` — **new**, ~150 lines

Modelled on `src/scraper.py`: same `config.GVIZ_URL`, same `config.FETCH_TIMEOUT`, same
`SheetStructureError` from `reader`, no credentials, read-only. **Do not** append
`GVIZ_NO_HEADER_COLLAPSE` (`config.py:129`) — this tab has one clean header row, exactly the
case that parameter is documented to break.

```python
@dataclass
class GuildBuildings:
    tab: str
    guild_key: str
    observed: bool                     # False = tab exists but has never been written
    captured_at: str = ""              # ISO-8601 from the sheet, "" when unobserved
    skill_levels: dict[str, int] = field(default_factory=dict)   # trial skill -> level
    shrine_levels: dict[str, int] = field(default_factory=dict)  # "force" -> level
    other_levels: dict[str, int] = field(default_factory=dict)   # combat/utility, by hrid
    ignored_hrids: list[str] = field(default_factory=list)
    def to_dict(self) -> dict: ...
```

- `fetch_buildings_csv(tab_name)` — byte-for-byte the shape of `scraper.fetch_tab_csv`
  (`scraper.py:73-97`), including the 401/403 "sharing may have been revoked" message.
- `parse_buildings(csv_text, guild_key, tab)`:
  - **Empty text or header-only ⇒ `GuildBuildings(observed=False)`.** Not an error. This is
    LI today (§2) and is the whole reason the flag exists: "unobserved" and "observed as all
    zeros" must not be the same value, even though both currently model to zeros.
  - Otherwise validate row 0 against `BUILDINGS_SENTINEL_HEADERS` by `==` after `strip()`
    and raise `SheetStructureError` on any mismatch, with the same "gviz silently serves a
    different tab" text `scraper._validate_gviz_header` uses (`scraper.py:100-125`). A
    wrong-tab serve fails this on cell 0 ("Building" vs `""`), which is the case measured in §2.
  - Cross-check every row's `Guild Id` against `config.GUILD_IDS[guild_key]`; a mismatch is a
    `SheetStructureError` naming both ids. This is the guard against the officers' tab map
    pointing a guild at the other guild's levels — silent, plausible, and the exact class of
    wrongness this repo keeps losing days to (`config.shrine_caps`' docstring says so).
  - Route by `Kind`: `building` hrids through `BUILDING_HRID_TO_SKILL` into `skill_levels`
    (unmapped → `other_levels`, keyed by hrid); `shrine` hrids' trailing segment into
    `shrine_levels`; any other `Kind` appended to `ignored_hrids`.
  - Levels through `reader._to_int` and clamped `0..GUILD_BUILDING_MAX_LEVEL`, so a
    malformed or future-inflated cell cannot inflate the model. A blank level is `0`.
  - `captured_at` = the **oldest** capture among the rows, matching
    `roster.Provenance.captured_at` ("OLDEST capture among the joined rows", `roster.py:394`).
- `scrape_buildings_tab(tab_name, guild_key) -> GuildBuildings` — fetch, guard, parse, wrap.

### 4.3 `src/trials.py` — one context manager, ~25 lines

Add `guild_building_levels_scope(levels)` directly beneath `community_buff_level`
(`trials.py:180-227`), sharing its save/restore shape:

```python
@contextmanager
def guild_building_levels_scope(levels: Optional[dict[str, int]]):
    """Run a block with the guild's LIVE building levels bound.

    ``levels`` of None or {} is a no-op, so an unobserved guild runs on
    config.GUILD_BUILDING_LEVELS exactly as before. Restored on the way out,
    exception or no. Same thread-safety contract as community_buff_level, and for
    the same reason: build._compute_unit is a process of its own.
    """
```

It rebinds the **whole dict** (`config.GUILD_BUILDING_LEVELS = {**saved, **levels}`) rather
than mutating items, so a `finally` that reassigns the saved object restores it whatever the
body did. Named `…_scope` because `guild_building_levels` is already a `WeekResult` field
(`trials.py:2386`) and reusing the name across a field and a context manager is how a reader
gets misled.

### 4.4 `src/build.py` — ~45 lines

1. **`GuildSite.buildings_tab`** property beside `shrine_caps` (`:133-142`), returning
   `config.BUILDING_TABS[self.key]`, with a docstring naming the writer (the Tampermonkey
   module via the Apps Script endpoint) and the fact that the tab may be empty.
2. **`_GuildInputs`** (`:4166-4198`) gains three fields, all picklable, all defaulted:
   `building_levels: dict[str, int] = field(default_factory=dict)`,
   `buildings_captured_at: str = ""`, `buildings_unavailable: str = ""`.
3. **`_fetch_guild`** (`:4407`) gains a block *after* the roster and *before* the sign-up
   tab, gated on `config.BUILDINGS_SOURCE_ENABLED`, catching `SheetStructureError` exactly as
   the roster block does (`:4440-4459`) — warn to stderr, record the reason, ship on the
   config fallback. A `RuntimeError` still propagates, unchanged. When the tab parses but
   `observed is False`, `buildings_unavailable` records "never written" rather than a failure,
   because the two are different things an officer would act on differently.
4. **`_unit_jobs`** (`:4873`) adds `"building_levels": inputs.building_levels` to `common`,
   under the existing comment's contract — resolved in the parent, shipped as plain data.
   It comes from `inputs`, not from `site`, because unlike `cap` it is *fetched* rather than
   configured.
5. **`_compute_unit`** (`:4554`) wraps its three `run_week` / `run_week_ladder` calls in
   `with trials_model.guild_building_levels_scope(job["building_levels"]):`. One `with`
   around the existing `if/else` — the counterfactual branch nests it inside
   `community_buff_level`, which composes cleanly (disjoint constants).
6. **The page must stop lying.** `build.py:2899-2901` currently reads "Building levels are
   entered by hand in `config.GUILD_BUILDING_LEVELS` for now, not read from the sheet". It
   becomes: read from this guild's Buildings tab, written from the game, with the capture
   date; and when `buildings_unavailable` is set, that reason. `_guild_buildings_footnote`
   (`:1754-1772`) is unchanged — it already renders from `week["guild_building_levels"]`,
   which now carries the live values.
7. **`_summary_line`** (`:4618`) gains one clause: the capture date and the count of built
   skilling buildings, or the unavailable reason — the same one-line CI visibility the roster
   join and the gear audit already get.

## 5. Tests

### 5.1 `tests/test_buildings.py` — **new**

Parser tests only; no network (fixtures are CSV strings, as `tests/test_scraper.py` does).

1. `test_parses_the_live_sc_block` — the real 28-row SC CSV, captured verbatim in the test
   file: Enhancing 1, the other nine skilling skills 0, five shrines 5/4/2/0/2,
   `captured_at` the ISO stamp, `observed is True`.
2. `test_empty_tab_is_unobserved_not_an_error` — `""` and header-only both give
   `observed is False`, empty `skill_levels`, and **no raise**. This is LI today.
3. `test_a_wrong_tab_serve_raises` — the 3518-byte first-tab junk measured in §2 must raise
   `SheetStructureError`. The regression this guard exists for.
4. `test_a_foreign_guild_id_raises` — SC rows with `Guild Id` 240 parsed as `"sc"` raises,
   and the message names both ids.
5. `test_levels_are_clamped_and_coerced` — `"999"` → 20, `""` → 0, `"-3"` → 0, `"abc"` → 0.
6. `test_unmapped_hrids_are_kept_apart_not_dropped_silently` — dojo/armory/guild_hall land in
   `other_levels`, never in `skill_levels`, and an unknown `Kind` is counted in `ignored_hrids`.
7. `test_hrid_map_covers_exactly_the_ten_skilling_buildings` — `set(BUILDING_HRID_TO_SKILL.values())`
   equals the ten modelled trial-skill keys of `GUILD_BUILDING_LEVELS`. Catches a typo'd
   skill name, which would otherwise silently grant nothing.

### 5.2 `tests/test_trials.py` — three added

8. `test_building_levels_scope_binds_and_restores` — inside the scope
   `guild_building_skill_levels("Enhancing") == 2`; outside, `0`; and the same after the body
   raises.
9. `test_building_levels_scope_is_a_noop_for_none_and_empty` — both leave the config object
   **identical** (`is` the same dict), which is the property the golden depends on.
10. `test_week_result_records_the_injected_levels` — `run_week` inside the scope emits
    `guild_building_levels["Enhancing"] == 1` in `to_dict()`, so the page renders what ran.

### 5.3 `tests/test_build.py` — **new**, two tests

11. `test_sequential_units_do_not_leak_levels_between_guilds` — `_compute_unit` twice on
    stub jobs with different `building_levels`, in-process (`BUILD_PARALLEL = False`), each
    asserting its own value and `config.GUILD_BUILDING_LEVELS` back to zeros between. This is
    the one real risk of the §3 decision, so it gets a test rather than an argument.
12. `test_unit_jobs_ship_the_fetched_levels` — `_unit_jobs` puts `inputs.building_levels`
    into every job.

### 5.4 Unchanged and must stay so

`tests/test_roster.py::test_roster_disabled_reproduces_the_golden_week` and
`tests/test_trials.py::test_guild_building_levels_all_zero_in_shipped_config` (`:203-207`)
are **not** touched. The second is now doing a second job — pinning the fallback — and gains a
comment saying so.

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | **The model moves.** SC Enhancing gains +2 levels, changing tiers, points, parties and the upgrade table. | Intended, but stated: §7 requires a before/after build diff on SC's `trials.json`, and the +2 must be the *only* mechanism in the delta. `BUILDINGS_SOURCE_ENABLED = False` reverts it in one line. |
| 2 | **gviz silently serves the wrong tab** on a renamed/deleted tab (`scraper.py:16-19`). | Six `equals` sentinels plus the `Guild Id` cross-check; test 3 uses the actual junk payload. |
| 3 | **Scope leak across guilds** in the sequential path, mis-crediting LI with SC's levels. | Whole-dict save/restore in `finally`; test 11. |
| 4 | **A stale tab read as current.** The tab is written only when a member running the module opens the guild panel; nobody who stops running it is thinking about this pipeline. | `captured_at` is parsed, carried to the page and the CI summary, and outlined past `ROSTER_MAX_AGE_DAYS` — a banner, not a cutoff (`config.py:301-306`). An old capture still beats the zeros it replaces. |
| 5 | **A second unreadable source takes down a required guild's deploy** (the failure mode `build.py:4443-4452` was written against). | `SheetStructureError` degrades to the config fallback with a warning; only network `RuntimeError` is fatal, as elsewhere. |
| 6 | **"Unobserved" collapses into "observed as zero"**, so LI's page claims a measurement it does not have. | `observed` is a distinct field; `buildings_unavailable` distinguishes *never written* from *failed to read*; test 2. |
| 7 | **`BUILDING_HRID_TO_SKILL` drifts** from the prose list, or from the game's hrids. | Test 7 pins it against `GUILD_BUILDING_LEVELS`' own keys; the prose at `config.py:1528` gains a pointer to the dict. A live hrid that is genuinely new lands in `other_levels` and is counted, never silently dropped. |
| 8 | **Scope creep.** The same tab carries the five shrine levels — SC force **5**, against `GUILD_SHRINE_CAPS["sc"]["force"] = 4`, which `config.py:1698-1702` admits is only an inferred *floor*. | Parsed into `shrine_levels` and carried, but **not wired to `GUILD_SHRINE_CAPS`** in this change. §8. |

## 7. Verification

1. `.venv/bin/python -m pytest tests/ -q` — full suite green; the golden and the 15
   dict-patching tests untouched.
2. `git stash && .venv/bin/python -m src.build && cp _site/trials.json /tmp/before-sc.json`,
   then unstash and rebuild. `jq` the two: SC's `guild_building_levels.Enhancing` moves
   `0 → 2`, every other skill stays `0`, and no field moves that `+2` in the success delta
   cannot explain. **LI's `trials.json` must be byte-identical** — its tab is empty, which is
   the cleanest available control.
3. `BUILDINGS_SOURCE_ENABLED = False` → SC's `trials.json` byte-identical to
   `/tmp/before-sc.json`. The rollback is verified, not asserted.
4. Eyeball `_site/trials.html`: the footnote reads "this week **Enhancing +2**", the prose
   names the tab and the capture date, and LI's says the tab has never been written.
5. Round-trip the parser against the live sheet, the check `apps-script/README.md:88-96`
   already prescribes for its sibling:
   ```bash
   uv run python -c "from src.buildings import scrape_buildings_tab as s; \
     print(s('SC Buildings','sc').to_dict()); print(s('LI Buildings','li').to_dict())"
   ```

## 8. Explicitly out of scope

- **Shrine caps from the tab.** SC's real cap is force 5 / tempo 4 / spirit 2 / rarity 0 /
  scholar 2 against the inferred floors of 4/4/2/0/2 — a genuine correction, affecting only
  the two page probes and nothing in the rate model (`config.py:1679-1681`). It is a
  *separate* change to `GUILD_SHRINE_CAPS` and `GuildSite.shrine_caps`, and folding it in
  would put two behavioural deltas in one diff and make risk 1's control worthless. The data
  is parsed and carried so the follow-on is a wiring change only.
- **The seven combat buildings** (dojo 4, armory 2, gym 1, archery range 1, mystical study 2
  on SC). This repo models the *skilling* race; those levels belong to the combat optimiser in
  `~/pie/SCLIRoster`, which reads them from its own `data/guild.json`. They are parsed into
  `other_levels` so the source exists when that side wants it.
- **`builders_hall` 6 / `treasury` 5 → the reward multipliers.** The tab gives the levels; the
  bonus *per level* is still unconfirmed, and inventing one is the fudge factor this project
  refuses. Blocked on a tooltip, not on code.
- **`combat_encampment` 3 → the sign-up seat cap.** Same shape: the level is now readable, the
  seats-per-level rule is not known.

## 9. Rollback

| Scope | Procedure |
|---|---|
| Behaviour, keeping the code | `config.BUILDINGS_SOURCE_ENABLED = False`. No fetch, no injection; every guild runs on `GUILD_BUILDING_LEVELS`. Verified by check 3. |
| One guild only | Remove its key from `config.BUILDING_TABS`; `_fetch_guild` records "no tab configured" and that guild falls back alone. |
| Everything | `git revert <commit>`. `src/buildings.py`, `tests/test_buildings.py` and `tests/test_build.py` are new files; every other change is additive except the `config.py` comment rewrite and the `build.py:2899` prose, neither of which is load-bearing. |

## 10. Order of work

`config.py` (4.1) → `buildings.py` + its tests (4.2, 5.1) → the context manager + its tests
(4.3, 5.2) → `build.py` wiring + its tests (4.4, 5.3) → prose and summary (4.4.6-7) →
verification (§7). Steps 1-3 are inert: nothing calls the new module until step 4, so the
suite is green after every one of them.
