# Implementation plan — per-item gear from the `gearSeen` union

**ResearchPack:** `research/per-item-gear.md` (measurements, decisions, and the
one judgement call recorded as a risk). **Evidence script:**
`research/scratch/gear_survey.py`. **Precedent:** this plan follows the shape of
`.claude/plans/roster-as-primary-source-implementation-plan.md` — the whole
mechanism lands dark, each slice is reconciled against an independent
measurement before the flip, and the flip is one line.

---

## 1. What changes, in one paragraph

Five terms in `trials.member_bonuses` are flat constants asserted of every
member: the cape (`CAPE_SPEED_PLUS3`), the family piece and the two garments
(`ARMOUR_EFFICIENCY_PLUS7` ×3), and the gathering doubling
(`GEAR_DOUBLE_CHANCE`); a sixth, the neck slot, is not modelled at all and is
carried in `RISK_SIGMA_SYSTEMATIC` as its largest single row. The `gearSeen`
column now reports, per member, which of 42 catalogue items they hold and at what
enhancement level. This change replaces the five constants and the one omission
with a per-item, per-skill computation from the catalogue, and recalibrates σ.

## 2. The one design decision worth arguing about

**The resolved gear terms are precomputed onto `MemberRow`, once per guild, in
the parent process.** `member_bonuses` then reads a dict rather than walking an
item table.

The alternative — resolving items inside `member_bonuses` — is wrong three ways.
It runs in the hottest loop in the project: `_prepare_member`'s docstring records
22.3 million calls per pipeline to compute ~1,200 distinct values. It would need
the per-guild imputation statistics as module state, and `config.py`'s
`BUILD_PARALLEL` note is explicit that the units run as **processes** precisely
because `trials.community_buff_level` already rebinds module globals — adding a
second rebinding target invites the bug that note exists to prevent. And it would
recompute a float sum 22 million times where one re-association is enough to send
the search down a different path (`_prepare_member`, "BIT-EXACTNESS").

Precomputing gives all three for free: plain picklable data on a dataclass
`_GuildInputs` already ships to the children, no new global state, one evaluation
per (member, skill) so the arithmetic cannot re-associate, and a hot path that
gets *faster* rather than slower. `calibrate.py` recomputes with perturbations
through the same function, exactly as `_perturbed_tool_terms` mirrors
`_tool_terms` today.

## 3. Files touched

| file | change |
|---|---|
| `src/gear.py` | **NEW.** The item table, the cell parser, the imputation statistics, the resolver. |
| `src/config.py` | The switch ladder, the column name, the excluded-slot rule. No item data — it lives in `gear.py` beside the code that reads it. |
| `src/reader.py` | `MemberRow.gear` (observations) and `.gear_bonuses` (resolved). Both omitted from JSON while unset. |
| `src/roster.py` | Parse the optional `gearSeen` column; carry it through the merge. |
| `src/trials.py` | `member_bonuses` and `_prepare_member` consume the resolved terms; `double_chance` becomes per-member. |
| `src/build.py` | Resolve once per guild beside `audit_roster_tools`; provenance; page. |
| `src/calibrate.py` | Respect the new provenance; perturb the imputed terms, not the observed ones. |
| `tests/` | `test_gear.py` new; additions to `test_roster.py`, `test_trials.py`. |
| `research/`, `README.md` | The pack (written); the reader-facing account. |

## 4. Phases

Each phase is a commit. Every phase up to G7 leaves published numbers **exactly**
as they are, pinned by the golden-week test.

### G0 — baseline (no code)
Record the published numbers before anything moves: step points per guild, the
per-trial margins and `P(holds)`, and `data.json`'s hash. This is what every later
phase diffs against, and what G6's reconciliation is measured from.

### G1 — `src/gear.py`, the table and the parser. Dead code.
- `GEAR_STATS`: the 42 non-tool race-relevant items, `hrid -> (slot, {skill:
  (channel, base, per)})`, transcribed from `research/item-stats.json` in the
  same discipline as `config.TOOL_STATS` — **and pinned by
  `test_gear_table_matches_item_stats_json`**, which regenerates it from the JSON
  and asserts equality. A test, not a promise.
- `test_gear_table_carries_no_loot_or_xp_stats`: no `Experience`, `RareFind`,
  `EssenceFind`, `taskSpeed` or `drinkConcentration` may appear, and the
  `trinket` and `pouch` slots may not appear at all. The twin of
  `test_tool_table_carries_no_loot_or_xp_stats`.
- `parse_gear_cell(text) -> dict[str, Optional[int]]`: blank -> `{}` ("we did not
  see"), `{"items": []}` -> a distinct sentinel for "we looked and they wore none
  of it". `apps-script/profiles/README.md` calls that difference out — "Blank is
  not empty" — and collapsing the two would lose the only signal that separates a
  gear-hider from a member in full combat kit.
- Nothing imports this module yet.

### G2 — read the column. Still dead.
- `config.ROSTER_GEAR_COLUMN = "gearSeen"`, and it is **OPTIONAL**:
  `roster.required_columns()` must NOT gain it. LI's tab lacked the column this
  morning and gained it by lunchtime; reverting the userscript would remove it
  again, and `apps-script/profiles/README.md` states that a narrower payload
  leaves the column untouched by design. A missing `gearSeen` must degrade to
  today's constants, never fail the header guard.
- `RosterRow.gear: dict[str, Optional[int]]`, parsed in `roster.parse`.
- A cell that will not parse is a `SheetStructureError` — the tab is
  machine-written, the same rule `_to_int_strict` already applies. Counted, and
  the member degrades to imputation rather than taking the build down.

### G3 — the statistics and the resolver. Gated OFF.
- `gear.ImputationStats.measure(rows, guild_key)`: the three per-guild statistics
  of ResearchPack §6.7 — pooled cape effective speed, per-item family-piece mean
  level, pooled garment mean level. **Computed, not transcribed**; §6.7 says why.
  Each carries its `n`, and a statistic with `n < GEAR_MIN_IMPUTE_N` falls back to
  the shipped constant rather than to a mean of two observations.
- `gear.resolve(member, stats) -> dict[skill, GearTerms]` applying ResearchPack
  §6 verbatim. `GearTerms` is a plain 4-tuple `(speed, efficiency, success,
  gathering)` — a tuple, for the reason `_prepare_member` returns one.
- Called from `_fetch_guild` beside `audit_roster_tools`, on the merged list.
- `MemberRow.gear_bonuses` populated. Nothing reads it.

### G4 — the consumer. Gated OFF, and pinned.
- `member_bonuses`: when `gear_bonuses` carries this skill, take the cape,
  family-piece and garment terms from it instead of the three constants.
- `double_chance` gains the member's gathering term; `_prepare_member` threads it.
- **`test_gear_disabled_reproduces_the_golden_week`** and
  **`test_data_json_is_byte_identical_with_gear_off`**, modelled on their roster
  twins. Note the roster golden's hard-won lesson (commit `526594b`): pure
  `+ - * / floor` compares on `==`, and only the two fields built from
  `math.erf` / `log` / `exp` get `rel=1e-12`. Do not loosen anything else.

### G5 — say it on the page. Still OFF.
`GearAudit` counters (members visible / hidden / blank-celled, items observed per
slot, imputations made per slot, unknown hrids), the provenance strip, and the
per-member badge. Renders "assumed" while the switch is off, which is the honest
description of today's build.

### G6 — reconcile each slice BEFORE the flip.
Four slices, each measured independently and each reconciled against a band
predicted from the ResearchPack's §7 table before it is allowed to ship:
cape (expect **up** ~11% on unobserved members), family piece (**down**, 0.1182 →
~0.107 SC / ~0.102 LI), garments (**down**), accessories (neck **up** for 88%,
ring/earrings **down** for ~half). A slice outside its band is a bug, not a
surprise — that is what this phase is for. Report per-guild step points and the
thinnest `P(holds)` for each slice in isolation.

### G7 — the flip. `GEAR_SOURCE_ENABLED = True`.
One line. Publish the before/after on step points and every trial's margin.

### G8 — recalibrate `RISK_SIGMA_SYSTEMATIC`.
- `calibrate.Sources.respect_provenance` must skip a draw for a (member, skill,
  slot) that is now **observed**, and must keep it where the term is **imputed** —
  and must add a NEW draw for the imputation error itself, which the previous σ
  did not carry. The neck row (0.0081–0.0110) is retired for the 88% observed and
  kept in full for the 24 unobserved and the 16 hiders.
- Same protocol as R6: the largest of the eight live trials, three seeds, 20 000
  reps, quote the max not the mean, and publish the `--ignore-provenance` control.
- A σ near zero is a **bug**; ResearchPack §7 says why.

### G9 — documentation.
`README.md` § "Where member data comes from"; the config comments; and close the
handover follow-ups this change resolves — `TOOL_ENHANCE_WHEN_UNKNOWN` (now
confirmed never exercised, 0 of 2,020) and the `stableGear` item (§11.2 of the
roster plan, now done).

## 5. The switch ladder, and the rollback

```
GEAR_SOURCE_ENABLED     = False  # MASTER. False -> no parse, no resolve, no new
                                 #   JSON keys, no page change. Bit-for-bit.
GEAR_USE_CAPE           = True   # per-item cape over CAPE_SPEED_PLUS3
GEAR_USE_FAMILY_PIECE   = True   # per-item boots/hat/watch/gloves
GEAR_USE_GARMENTS       = True   # per-item top/bottoms over the flat +7
GEAR_USE_ACCESSORIES    = True   # neck/ring/earrings, previously unmodelled
GEAR_IMPUTE_FAMILY_PIECE= True   # False -> own only where SEEN. The evidence-led
                                 #   reading of ResearchPack §3.1; the one line
                                 #   that reverses this change's largest judgement.
GEAR_GATHERING_IN_RATE  = True   # False -> price every gatheringQuantity item at
                                 #   zero, isolating config.py §1177's open
                                 #   question, which the flat constant could not.
GEAR_MIN_IMPUTE_N       = 10     # below this, an imputation statistic is refused
                                 #   and the shipped constant is used instead.
```

There is deliberately **no** `GEAR_UNKNOWN_ITEM_FATAL`, unlike the roster's
`ROSTER_UNKNOWN_TOOL_FATAL`. The asymmetry is argued where the switch would have
gone, in `config.py`: a tool column is a *named slot* so an unrecognised item
there is a new tier or a shifted header, whereas the gear union is a flat list and
the only catalogue this repo carries has no combat items in it at all.

**Rollback procedure.** `GEAR_SOURCE_ENABLED = False` restores the pre-change
build bit-for-bit, pinned by two tests, and — as with the roster — the gating is
at the **parse**, so the rollback also covers the case where the upstream
userscript or the Apps Script merge is the thing that is broken. For a partial
rollback, each slice has its own switch, so an adverse slice can be reverted
without losing the other three. Restoring `RISK_SIGMA_SYSTEMATIC` to 0.0123 is a
separate one-line revert and G8 will record the previous value in the comment, as
R6 recorded 0.0131.

## 5b. What changed during implementation

Three decisions in §4 and §5 did not survive contact with the code. Each is
recorded here rather than quietly amended, because the reasoning is the useful
part.

**`GEAR_UNKNOWN_ITEM_FATAL` was withdrawn, not implemented.** §5 listed it by
analogy with `ROSTER_UNKNOWN_TOOL_FATAL`. The analogy fails: a tool column is a
*named slot*, so an item `TOOL_STATS` does not know is either a new tier or a
shifted header. The gear union is a flat list of whatever was equipped, and
`research/item-stats.json` carries only the 188 items that *have* non-combat
stats — combat gear is absent altogether — so the check would flag every Chaotic
Flail and Anchorbound Plate, some sixty per guild, none actionable. The count is
reported as **unmodelled** rather than unknown, and the argument sits in
`config.py` where the switch would have gone.

**The imputation error is resampled, not perturbed by a half-width.** §4's G8
implied a new `Sources` half-width. Wrong instrument: asserting "this member holds
the guild mean" when the truth is one draw from the guild's own distribution is
exactly the case `Sources.house_blank` already handles for a blank `H` cell — "the
posterior predictive given no information, which also removes the flat default's
bias for free". A half-width would have to be invented, would be symmetric about a
mean that is itself the estimate, and would get the shape wrong.
`gear.ImputationStats` therefore keeps the pools behind its three means, and
`gear_impute_resample` draws from them.

**Neither gear field is serialised.** Measured on the live SC roster, the raw union
costs 57 KB and the resolved bonuses another 59 KB against a 256 KB members
payload — a 45% increase to a file the browser fetches on every page load, for two
fields nothing on any page reads. `gear_bonuses` is a cache of `gear` plus the
catalogue; `gear` waits for the per-member badge that will use it, at which point
deleting one line in `reader._NEVER_SERIALISED` is the whole change.

**And one measurement note for whoever runs G6 again.** Buffer your output:
`research/scratch/gear_reconcile.py` writes nothing to a redirected file until it
exits, so a forty-minute run looks indistinguishable from a hung one. Run it with
`python -u`.

## 6. What could go wrong, and what it would look like

| risk | symptom | mitigation |
|---|---|---|
| The family-piece imputation is wrong (ResearchPack §3.1) | half the guild over-credited 0.1182 efficiency; parties that hold on paper and fail in fact | `GEAR_IMPUTE_FAMILY_PIECE = False`; re-run survey §4 in a few weeks and watch the "0 of four" column |
| The union has not converged, so absences are artefacts | accessories under-credited for members who own them | accessories are never imputed *by decision*; the error is one-sided and conservative |
| `skillingEfficiency` does not in fact reach enhancing | enhancing over-credited for 117 members | isolable: it is one row of `GEAR_STATS`; a capture of an enhancing trial's `efficiency` field settles it |
| A new race-relevant game item appears | it hides among the ~60 combat hrids the union carries and is silently unpriced | counted as `unmodelled_items`, never guessed. **There is deliberately no fatal switch** — `item-stats.json` holds only the 188 items *with* non-combat stats, so an "is this known?" test would flag every Chaotic Flail. The real mitigation is a fresh catalogue dump compared by `test_gear_table_matches_item_stats_json`; see config.py's note where the switch would have gone. |
| Statistics computed from too few observations | a garment mean built on n=1 | `GEAR_MIN_IMPUTE_N`, and §6.7's pooling |
| Bit-exactness lost in the hot loop | search reshuffles every party for no gain | terms precomputed once (§2); golden test on `==` for everything but the two `erf`/`log` fields |
