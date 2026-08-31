# 🗺️ Implementation Plan: the scripted Roster tabs as the PRIMARY member-data source

**Status:** plan only — nothing implemented.
**ResearchPack:** `.claude/plans/roster-as-primary-source-researchpack.md` (live-verified
2026-08-31). Every figure it measures is taken as given here and is not re-derived.

---

## Summary

Two new tabs — `SC Roster` (107 × 78) and `LI Roster` (105 × 78) — are written by the
`profiles-endpoint` Apps Script from a per-character harvest. They carry, per member and
per skill, the three things the model currently reads off a hand-maintained tab
(**level**, **house level**, **tool tier**) plus one thing it has never had and has been
*assuming* since Phase 1: **the tool's enhancement level**.

It also carries a second thing the model has been getting wrong, and getting wrong for
almost everybody: **each member's own purchased guild-shrine levels**. The guild buys the
*right* to a shrine level; the member then spends their own resources to take it. The guild
level is a **cap**; `shrine_<name>_skilling` is the member's purchase; and it is the
purchase, not the cap, that enters the rate. `config.GUILD_SHRINE_LEVELS` models that as one
guild-wide constant of `1`, and between **88% and 95%** of members hold something else (§2.2).

This plan makes the roster the primary source for all of it, keeps the manual tab as a
**per-field** fallback, and keeps the existing constants as the last resort.

**The thesis, in one sentence.** Four per-member quantities that the model currently
*assumes* are all separately observable on the roster, they are wrong by different amounts
in different directions, and — because the optimizer's entire job is ranking members into
seats — an unmodelled spread *between* members is a rank-order error rather than a scaling
one. Levels are stale (up to +17 on LI), shrines are modelled at 1 against a mean of ~3,
tool enhancement is assumed `+7` against an observed mode of `+5`, and houses are guessed at
4 against a measured ~3.1. Correcting all four is worth **+3.30% (SC) / +6.00% (LI)** of
mean per-member rate, and the four terms do not point the same way (§2.2) — which is what
makes the decomposition in R5 the load-bearing part of this plan rather than a formality.

**Key architectural decision — the merge is the implementation.** Levels and houses do
not need a single line of new code in `trials.py`. `roster.py` produces a **new
`list[MemberRow]`** in which the roster's values have already been written into
`SkillEntry.level` and `SkillEntry.house`, with a provenance tag beside them. Everything
downstream — `member_bonuses`, `_prepare_member`, `simulate_race`, the optimizer,
`signup.py`, `calibrate.py` — is untouched and reads better numbers out of the fields it
already reads. Only **tools** need new logic, because a tool is no longer a boolean.

**Consequence for the hot loop: none.** The merge happens once per guild, in the parent
process, beside the existing fetches (`build._fetch_guild`). `_prepare_member` gains zero
work; `simulate_race` gains zero work. The ~5m34s optimise phase is unchanged, and the
plan pays one extra ~1s gviz GET per guild.

**Second architectural decision — the register is not the model.** `index.html` continues
to be built from the *unmerged* rows. It is the mirror of the officers' own sheet and its
job is to show them what their sheet says, stale cells included; that is the page an
officer uses to notice a stale cell. `trials.html` and `signup.html` are the model and use
the merged rows. The two pages answer different questions and conflating them would
destroy the one that reports data quality.

**Expect the headline totals to RISE** — and treat that as the more dangerous direction,
not the safer one. Three of the four slices are favourable and only the tool repricing is
adverse, so the net is **+3.30% / +6.00%** of member rate. Good news is what nobody audits.
The whole verification discipline in R5 therefore exists to stop this landing as an
unexamined improvement: every slice must hit a band predicted by an independent
measurement, *including* the three that go up, and slice 4's negative sign is the specific
evidence that the change is a correction rather than a uniform coat of optimism.

**Rollback.** `ROSTER_SOURCE_ENABLED = False` restores today's build bit-for-bit — no
fetch, no merge, no new JSON keys, no second HTTP request — pinned by a golden test (§8).
Four finer switches allow a partial revert without giving up the parts that work.

---

## 1. Scope

| In | Out |
|---|---|
| **new** `src/roster.py`, `tests/test_roster.py` | any Google **write**; any credential |
| `src/config.py` (roster tab map, tool table, switches) | the `stableGear` 14-column gear block (§11.2) |
| `src/reader.py` (`SkillEntry` / `MemberRow` optional fields) | Top / Bot — permanently manual (§11.3) |
| `src/trials.py` (tool precedence, per-member shrines, both shrine probes) | combat, boss trials, guild credits |
| `src/build.py` (`_fetch_guild`, provenance rendering, caveats) | the optimizer's search, any objective change |
| `src/calibrate.py` (provenance-aware `Sources`, one re-run) | `index.html` / `data.json` register content (§ Summary) |
| `src/scraper.py` (reuse `fetch_tab_csv`; `to_dict` key filter) | the shrine *cost* ladders and guild-point economics |
| `README.md`, `research/roster-as-primary-source.md` | the party-cap question (still open from the prior plan §3.7) |

---

## 2. Facts this plan builds on (from the ResearchPack — do not re-derive)

Restated only where a step below depends on the exact figure.

- The roster tab is addressable by **name** through the existing `config.GVIZ_URL`; the
  header row comes back clean. **Do not append `GVIZ_NO_HEADER_COLLAPSE`** — it blanks the
  label of every numeric column, which is most of the tab.
- Tool-block **column order varies** with whether the upstream module had client data.
  Read by header name.
- **Blank ≠ zero**, and the endpoint preserves the difference: `0` = catalogue item never
  acquired, blank = withheld (`hideWearableItems`) or unknown.
- The join must be **case-insensitive**: exact matching loses 6 members on each guild;
  case-insensitive recovers 107/107 on SC and 100/101 on LI.
- **9 of 107 SC** and **7 of 105 LI** hide gear: all 20 tool columns blank, skills/houses/
  shrines still populated. This is the case that forces per-field precedence.
- Manual levels are stale, badly on LI: seven LI members are **5–17 levels** above what the
  model believes.
- LI leaves **59 of 88** house cells blank, currently defaulting to `DEFAULT_HOUSE_LEVEL =
  4` against a measured filled-cell mean of ~3.1 — a bias `calibrate.py:392` already knows
  about.
- The "Tool" checkbox faithfully means Celestial (SC 127/130 ticks agree; LI 58/62).
- **Shrines are a per-member purchase under a per-guild cap** (§2.2) — the correction that
  reverses this plan's headline direction.
- Observed enhancement (SC): `{0:6, 3:16, 4:38, 5:298, 6:139, 7:254, 8:92, 9:29, 10:91,
  11:12, 12:3, 13:1, 14:1}`; LI modal `+5`. Repricing against `+7` on the speed channel
  alone: **mean −0.66% (SC) / −1.50% (LI)**, p05 −3.8%/−4.9%, p95 +4.6%/+3.2%, range
  −11.19% … +13.52%. (§2.3 supersedes this as the authoritative figure and says why.)

### 2.1 One finding this plan adds to the ResearchPack

The ResearchPack calls Rainbow / Azure / Burble / Cheese "tool tiers the current binary
cannot express" and asks that an unknown tier degrade safely. **They are not unknown.**
`research/item-stats.json` already carries every tool in the game at every tier, each with
both terms the model needs:

```
/items/holy_brush       noncombatStats.milkingSpeed 0.9    noncombatEnhancementBonuses.milkingSpeed 0.018
/items/celestial_brush                              1.05                                            0.021
/items/rainbow_brush                                0.75                                            0.015
/items/burble_brush                                 0.45                                            0.009
/items/azure_brush                                  0.30                                            0.006
/items/cheese_brush                                 0.15                                            0.003
/items/celestial_enhancer  enhancingSuccess 0.042                enhancingSuccess 0.00084
/items/rainbow_enhancer                     0.03                                  0.0006
```

The first two rows are exactly `calibrate.TOOL_SPEED_HOLY = (0.9, 0.018)` and
`TOOL_SPEED_CELESTIAL = (1.05, 0.021)`. So the generalisation is a **table lookup keyed by
item name**, evaluated through the same `base + MULT[level] * per` rule
(`calibrate._stat`), and the existing four constants become two rows of it. There is no
approximation to make and no tier to guess. The "unknown item" path (§5.3) is therefore
reserved for its real purpose: an item the *game* adds after this table was transcribed.

### 2.2 Shrines: the mechanic, corrected

**The guild's shrine level is a cap, not a grant.** The guild purchases the *ability* to
upgrade a shrine; the member then spends their own resources to actually obtain the
upgrade. A guild may unlock level 5 while a given member can only afford level 3, and it is
**that member's level 3** that improves their stats. `shrine_<name>_skilling` on the roster
is the member's own purchased level.

The live data corroborates it exactly — every member sits at or below a per-guild ceiling,
and the ceiling differs between the two guilds:

| | `force_skilling` | `tempo_skilling` | spirit | scholar | rarity |
|---|---|---|---|---|---|
| **SC** (n=107) | `{0:5, 1:13, 2:13, 3:23, 4:53}` — mean 2.99, **max 4** | `{0:7, 1:6, 2:12, 3:23, 4:59}` — mean 3.13, **max 4** | max 2 | max 2 | all 0 |
| **LI** (n=105) | `{0:10, 1:5, 2:34, 3:56}` — mean 2.30, **max 3** | `{0:10, 1:7, 2:28, 3:60}` — mean 2.31, **max 3** | max 1 | max 1 | all 0 |

The per-guild **maximum is the guild's unlocked cap** (SC 4, LI 3). No member exceeds it;
many sit below it, which is the population who can improve their own rate with no guild
spend at all (§5.5).

Three consequences, and each is larger than the tool repricing this plan was originally
organised around.

1. **`config.GUILD_SHRINE_LEVELS = {"force": 1, "tempo": 1}` is not merely stale and not
   merely per-guild-wrong — it is the wrong *shape*.** It models as one guild-wide constant
   a quantity that is a per-member purchasing decision. Counting members whose level is
   anything other than the modelled 1: SC force 94/107 (88%), SC tempo 101/107 (94%),
   LI force 100/105 (95%), LI tempo 98/105 (93%). The error is mostly in the understating
   direction — SC's mean force level is 2.99 against a modelled 1.0 — but not uniformly:
   5 SC and 10 LI members hold level 0, for whom the model currently *overstates*.
2. **It answers the open question recorded at `config.py:1136-1141`**, which asks which of
   two ladders drives the multiplier — the shrine level bought with guild points, or the
   buff level bought with guild tokens and credits. The answer is *both, in series*: the
   shrine level is the guild's **cap**, the buff level is the member's **purchase**, and it
   is the purchase that reaches the rate. That question is retired by this change, with the
   roster column as its resolution, and R7 must delete the comment rather than leave a
   settled question sitting in config looking open.
3. **`probe_shrine_upgrade` inverts its own meaning** — §5.5.

### 2.3 The four slices, measured through this repo's own rate path

Re-measured through `trials._prepare_member` / `trials.success` at tier 11, over every
matched member × skill — *not* re-derived from first principles:

| slice | SC mean | SC median | SC p05 / p95 | LI mean | LI median | LI p05 / p95 |
|---|---|---|---|---|---|---|
| 1 — levels (roster vs manual) | **+2.41%** | +0.00% | +0.00 / +13.19 | **+6.57%** | +0.81% | +0.00 / +27.64 |
| 2 — houses | +0.03% | +0.00% | +0.00 / +0.00 | −0.16% | +0.00% | −2.14 / +1.41 |
| 3 — shrines (per-member vs global L1) | **+1.33%** | +1.40% | −0.23 / +2.30 | **+0.89%** | +1.13% | −0.23 / +1.70 |
| 4 — tools (real tier + enh vs assumed +7) | **−0.52%** | +0.00% | −3.79 / +4.55 | **−1.26%** | −1.35% | −4.89 / +4.55 |
| **all four combined** | **+3.30%** | +1.75% | −2.85 / +14.29 | **+6.00%** | +2.05% | −3.69 / +26.81 |

**70% of SC slot-observations and 63% of LI's get faster.** The tool-augment pessimism is
real, and it is the only adverse term; it is outweighed roughly four-to-one by stale levels
and understated shrines.

Note also that the combined figure is not the sum of the parts (SC 3.30 vs 3.25; LI 6.00 vs
6.04). That residual is the interaction term, it is small, and R5 uses it as a check: a
large interaction would mean one of the slices is not doing what its name says.

**Which tool figure is authoritative.** The ResearchPack's §5 gives `−0.66% (SC) / −1.50%
(LI)` for the tool slice; the table above gives `−0.52% / −1.26%`. **The table above is
authoritative**, because it is measured through the repo's own rate path — it includes the
Enhancing **success** channel (where a tool feeds `success_bonus`, not speed) and the
`math.floor(work_power(...))` step in `_prepare_member`, both of which the ResearchPack's
simpler speed-channel-only calculation omits. The ResearchPack figure remains useful as an
independent cross-check on the speed channel alone, and the ~0.15pp gap between the two is
itself expected and explained; a *third* number matching neither would not be.

---

## 3. Non-negotiables, and how each is discharged

| Constraint | Discharged by |
|---|---|
| credential-free, one-directional, public CSV only | `roster.fetch` calls `scraper.fetch_tab_csv(tab)` — the existing function, the existing `GVIZ_URL`. No new network code, no key, no write. Step R1.2. |
| per-**field** precedence, not per-member | The merge resolves each field independently and records a per-field provenance tag. The gear-hider case (`test_gear_hider_keeps_roster_levels_and_manual_tools`) is the pinning test. Step R2.3. |
| read columns by **header name** | `roster._index_header` builds `{name: col}` from row 0; the parser never sees an integer index. Plus a slot cross-check (§5.3) that catches a remap the name lookup could not. Step R1.3. |
| a **structure guard** in the spirit of the sentinels | `roster._validate_header` requires **every** column named in `config.ROSTER_COLUMNS` to be present, by exact name. A header change fails loudly — but degrades rather than stopping the deploy (§9, Risk 2). Step R1.4. |
| join **case-insensitive**, unmatched reported | Reuses `signup._norm_name` (casefold + collapsed whitespace) and its ambiguity rule. Both directions reported, in the shape `build.py:3784-3801` already uses. Step R2.2. |
| a named one-line rollback per behavioural change | Nine switches, §6. Master: `ROSTER_SOURCE_ENABLED = False`, pinned by a golden test. |
| surgical; no per-race work added | The merge is once-per-guild in the parent. `_prepare_member`'s signature, body and tuple shape are untouched. Priced in §7.5. |

---

## 4. File changes (2 new, 7 modified, 1 new test file, 1 new research note)

### New

**`src/roster.py`** (~260 lines) — fetch, structure guard, parse, join, merge. Pure logic
plus one reuse of `scraper.fetch_tab_csv`. No HTML, no file I/O.

**`tests/test_roster.py`** (~450 lines) — offline, inline gviz-shaped fixtures in the style
of `tests/test_scraper.py`.

**`research/roster-as-primary-source.md`** — the four-slice measurement table, the
before/after tier tables, the sigma ablation, and the open questions in §11.

### Modified

| file | change |
|---|---|
| `src/config.py` | `ROSTER_TABS`, `ROSTER_COLUMNS` (the skill → level/house/tool column map plus the five `shrine_*_skilling` singletons), `TOOL_STATS` + `ENHANCEMENT_MULT_TABLE` (transcribed, pinned), nine switches; `GUILD_SHRINE_LEVELS` split per guild and re-pointed at the guild **cap** (R7.1), with the now-answered open question at `:1136-1141` deleted. **No existing constant is deleted otherwise** — `TOOL_SPEED_*_PLUS7` etc. remain, as the fallback and as the pinned identity. |
| `src/reader.py` | `SkillEntry` gains `tool_item`, `tool_enhance` (both `Optional`, default `None`); `MemberRow` gains `character_id`, `captured_at`, `shrine_levels` (`dict[str, int]`, default empty), `provenance` (`dict[str, str]`, default empty). All defaulted, so every existing constructor call is untouched. |
| `src/scraper.py` | `GuildData.to_dict` omits the new keys when they are all unset, so `data.json` is byte-identical with the switch off. Nothing else. |
| `src/trials.py` | `_resolve_tool(member, skill)` (new sibling, ~20 lines); `tool_bonus(skill, item, enhance)` (new, ~25 lines); `member_shrine_bonuses(member, overrides)` (new, ~25 lines); ~20 lines inside `member_bonuses` replacing the two `if tool` branches and the shrine resolve; the hoist removed at `simulate_race:1198`, `:771`, `:855`; `probe_shrine_upgrade` re-specified and `probe_shrine_adoption` added (§5.5). `_resolve_level_and_checks` keeps its 5-tuple **unchanged** — `calibrate.py:369` unpacks it. `MemberBonuses` is untouched: its `shrine_speed` / `shrine_efficiency` fields already exist and are already applied at the point of use. |
| `src/build.py` | `GuildSite.roster_tab` property beside `member_tab`; the roster fetch + merge + admission in `_fetch_guild` (merged list for the model, unmerged for the register, so `index.html` keeps mirroring the manual tab); provenance counters onto `_GuildInputs`; the provenance strip + per-member marks + tool-tier badge in the renderers; **edits** to the `Assumptions & caveats` block (`:2115`) and the sigma sentence (`:3276`); the join NOTE/WARNING beside the existing sign-up ones. |
| `src/calibrate.py` | `Sources.respect_provenance: bool = False`; `_prepare_perturbed` skips `augment` / `tool_flip` for a roster-backed tool and `house_blank` for a roster-backed house. One re-run, one new `RISK_SIGMA_SYSTEMATIC`. |
| `README.md` | a "Where member data comes from" subsection: the three-tier precedence, the switch ladder, the measured before/after. |

---

## 5. The six decisions that carry the plan

### 5.1 A new `src/roster.py`, not an addition to `scraper.py`

`scraper.py` is written, top to bottom, against **one** table shape: 58 columns, ten
5-column skill blocks at a fixed stride, positional offsets, sentinels by column index. Its
module docstring is an argument about that shape. The roster tab shares none of it — 78
columns, one row per character, header-name addressing, a column order that legitimately
varies. Putting both in one module would give it two column models, two structure guards
with contradictory rules ("match by index/substring" vs "match by exact name"), and a
docstring that could no longer state what the module reads.

The repo has already settled this question three times: `draw.py` reads one tab shape,
`signup.py` another, `scraper.py` a third, and each is its own module with its own guard
and its own account of its own gotchas. `roster.py` is the fourth, by the same rule.

What it must **not** do is duplicate the network path. `scraper.fetch_tab_csv(tab_name)` is
already parametrised by tab name, already url-encodes, already carries the 401/403 message
about revoked sharing. `roster.py` imports it. There is exactly one place in this
repository that talks to gviz and it stays that way.

### 5.2 The merge writes into `SkillEntry`; nothing else changes shape

`simulate_race` never sees a `MemberRow`, and the only thing that does is
`member_bonuses` → `_resolve_level_and_checks` → `member.skills[col]`. So the carrier for
roster facts is `SkillEntry` itself.

```python
@dataclass
class SkillEntry:
    level: Optional[int]
    tool: bool
    top: bool
    bot: bool
    house: Optional[int] = None
    # --- roster-sourced; None means "the roster did not say" --------------
    tool_item: Optional[str] = None      # e.g. "Celestial Brush"
    tool_enhance: Optional[int] = None   # observed enhancement level, 0..20
```

and on `MemberRow`: `character_id`, `captured_at`, `provenance: dict[str, str]`.

**Levels and houses need no consumer change at all.** `roster.merge` overwrites
`SkillEntry.level` and `SkillEntry.house` in the copy it returns; `_resolve_level_and_checks`
reads the same two fields it always read and gets better numbers. That also means the
per-trial minimum-level eligibility rule (`trials.member_skill_level` →
`trials.meets_min_level`) becomes roster-backed for free, which is correct: the game gates
on the character's own skill level, and the roster is the more accurate reading of it.

Why fields on the dataclass rather than a side-table keyed by name: `MemberRow` is what
gets passed through `member_bonuses`, `rate`, `simulate_race`, `AssignmentScorer`,
`signup.plan`, and `calibrate._prepare_perturbed` — which rebuilds members with
`dataclasses.replace`. A side-table would have to be threaded through all of it, which is
precisely the argument `trials.community_buff_level`'s docstring already makes against
threading a parameter, and `calibrate`'s perturbation would silently lose the roster facts
on the way through. Optional fields with defaults cost nothing and are picklable, which
`BUILD_PARALLEL = True` requires.

The one price is `data.json`: `asdict` would emit `"tool_item": null` on every skill of
every member even with the roster off. `scraper.GuildData.to_dict` therefore filters the
roster keys out when they are unset — one function, pinned by
`test_data_json_is_byte_identical_with_roster_off`. The alternative (accept the null keys)
would make the byte-for-byte rollback claim false, and this repo's rollback claims are
pinned by tests rather than asserted in prose.

### 5.3 Tools: a table keyed by item name, a slot cross-check, and a visible unknown path

`member_bonuses` today:

```python
speed += config.TOOL_SPEED_CELESTIAL_PLUS7 if tool else config.TOOL_SPEED_HOLY_PLUS7
```

becomes a four-step precedence, per member **per skill**:

1. **Roster named a known item and gave an enhancement level** → `tool_bonus` evaluates
   `base + ENHANCEMENT_MULT_TABLE[level] * per` from `config.TOOL_STATS[item]`. Provenance
   `roster`.
2. **Roster named a known item, enhancement blank** → the same, at
   `config.TOOL_ENHANCE_WHEN_UNKNOWN` (shipped **0**, argued below). Provenance
   `roster-partial`; counted and printed.
3. **Roster named an item that is not in the table** → do **not** guess a tier. Fall back
   to the manual checkbox, tag provenance `manual (unknown item: <name>)`, increment a
   counter, print `WARNING (<guild>): N unknown tool item(s)…`, and render the member's
   tool badge outlined with the raw item name in its title. Not fatal by default
   (`ROSTER_UNKNOWN_TOOL_FATAL = False`) — one new game item must not stop a deploy — but
   never silent, and never scored as Holy without saying so.
4. **Roster blank** (the gear-hiders) → the manual checkbox → today's two constants,
   unchanged. Provenance `manual`.

**`config.TOOL_STATS` is transcribed into config, not read from `research/`.** `config.py`'s
own header states the rule: numbers are transcribed "so the model has no runtime dependency
on the research directory". The table is generated once from `research/item-stats.json`
(60 tools × `(channel, base, per)`) and **pinned by a dev-only test** that regenerates it
and asserts equality — the same discipline `calibrate._load_multiplier_table`'s two asserts
already apply to the multiplier curve, generalised to the whole table. Two further asserts
pin the identity that makes this a refactor rather than a rewrite:

```
tool_bonus("Milking",   "Holy Brush",         7) == (config.TOOL_SPEED_HOLY_PLUS7, 0.0)
tool_bonus("Milking",   "Celestial Brush",    7) == (config.TOOL_SPEED_CELESTIAL_PLUS7, 0.0)
tool_bonus("Enhancing", "Holy Enhancer",      7) == (0.0, config.TOOL_SUCCESS_HOLY_PLUS7)
tool_bonus("Enhancing", "Celestial Enhancer", 7) == (0.0, config.TOOL_SUCCESS_CELESTIAL_PLUS7)
```

Exact equality, not `approx`. `_prepare_member`'s docstring explains why a one-ULP change
matters here.

The table carries **only** the race-relevant stat. Celestial tools also grant
`<skill>RareFind` and `<skill>Experience`; those buff loot and XP and must not enter the
rate model, for exactly the reason `guild_shrine_bonuses` refuses Rarity, Spirit and
Scholar. The generator selects by stat key (`<skill>Speed` for the nine, `enhancingSuccess`
for Enhancing) and the pinning test asserts the table has no other keys.

**The slot cross-check is the guard the name lookup cannot provide.** The ResearchPack warns
that the tool block's column order varies. Reading by header name handles a *reordering*;
it does not handle the case where the header row itself is shifted relative to the data
(the classic off-by-one that a name lookup happily produces plausible-looking values for).
So: every item read from `tool_<skill>` is checked against `TOOL_STATS[item].skill`, and a
"Celestial Spatula" appearing under `tool_milking` raises `SheetStructureError`. Cheap,
total, and it catches precisely the failure the ResearchPack flags.

**`TOOL_ENHANCE_WHEN_UNKNOWN = 0`, and it is provisional.** Blank means the module did not
report a level, and the repo's standing habit with an unknown is to err in the direction
that cannot flatter the answer (`calibrate.DEFAULT`'s `level_common=0` comment makes the
same argument at length). `0` understates against an observed mode of `+5`, so if this case
is common the choice is wrong in a way that matters. It is therefore **counted and printed
every build**, and §11.6 makes retiring it an explicit open question with a numeric
trigger: if the count exceeds 5% of matched member-skills on either guild, resolve it
before R5's flip rather than after.

### 5.4 Shrines become per-member — a correctness fix, not a refinement

§2.2 establishes the mechanic: the guild level is a **cap**, the member's purchased level is
what enters the rate, and the roster column is that purchased level. The model currently
holds every member at level 1 and is therefore wrong for **88–95% of them**, worth
**+1.33% (SC) / +0.89% (LI)** of mean per-member rate — the second-largest of the four
slices. This is not an optional refinement to be deferred behind the tool work; it is a
correctness fix to a value the model gets wrong for almost everybody, and it is sequenced
accordingly (§7: implementation in R3, measurement as slice 3 of R5).

**How it is implemented, and the bit-exactness constraint that governs it.**

`MemberBonuses` already carries `shrine_speed` / `shrine_efficiency` as **separate fields**,
and `_prepare_member` already applies them *at the point of use*:

```python
math.floor(work_power(b.level, b.efficiency + b.shrine_efficiency)),
action_seconds(skill, b.speed + b.shrine_speed),
```

That shape was chosen so `MemberBonuses` keeps saying what the member owns — and it is
already exactly the shape per-member shrines want. **The change is to how those two fields
are populated, not to where they are applied.** Do *not* fold shrines into `b.speed` /
`b.efficiency`: `_prepare_member`'s docstring records a live incident in which
re-associating this arithmetic moved a party rate by one ULP and sent the optimizer down a
different path — SC kept its 4800 points and reshuffled every party for no gain. The
addition order is preserved exactly, and §8.4 pins it with an exact-`==` test.

Concretely:

- **`MemberRow` gains `shrine_levels: dict[str, int]`**, populated at merge time from the
  five `shrine_*_skilling` columns. **Levels, not resolved bonuses** — so that
  `SHRINE_BUFFS_APPLY_IN_TRIALS` and the `GUILD_SHRINE_SKILLING_BUFFS` channel table are
  still read at *call* time, which is the property the whole rate model depends on and
  which `community_buff_level`'s docstring is explicit about.
- **New `trials.member_shrine_bonuses(member, overrides=None) -> tuple[float, float]`** —
  the per-member twin of `guild_shrine_bonuses`, dispatching on the *same* channel table so
  a loot or XP shrine (Rarity, Spirit, Scholar) still cannot reach the race and a future
  shrine still cannot be silently misapplied. Returns `(0.0, 0.0)` under
  `SHRINE_BUFFS_APPLY_IN_TRIALS = False`, exactly as its twin does.
- **`member_bonuses`'s existing `if shrine is None: shrine = guild_shrine_bonuses()`**
  becomes a two-way resolve on `ROSTER_USE_SHRINES`. The `shrine is None` convention already
  means "resolve it yourself"; nothing new is invented at the call site.
- **`simulate_race:1198` must stop hoisting.** `shrine = guild_shrine_bonuses()` resolved
  once per race and handed to every member is precisely the optimisation that per-member
  data invalidates. Under `ROSTER_USE_SHRINES` it passes `None`; with the switch off it
  hoists exactly as today, bit-for-bit. The same applies at `:771` and `:855`.

**The cost, priced honestly.** `member_bonuses` already runs **once per member per race** —
`_prepare_member` calls it, and `_prepare_member` is called once per member per race, not
once per tier. The added work is therefore one dict read and at most two multiplications per
member per race, against a `success()` call that already runs ~13 times per member per race
inside the tier loop. Removing the hoist costs the *difference* between one resolve per race
and one per member per race, which is ~24 dict reads.

An earlier draft of this plan leaned on a performance objection to defer this work. That
objection was weak then and is weaker now that the hoist has to go regardless, and it should
not have been offered — the honest reason to hesitate was semantic (which of three things
does a per-member column for a guild-wide buff mean?), and §2.2 has discharged it.

### 5.5 `probe_shrine_upgrade` inverts, and a better probe falls out of the correction

`probe_shrine_upgrade` (`trials.py:1653`) prices "one more guild shrine level" by rebinding
`config.GUILD_SHRINE_LEVELS` and re-racing — i.e. by assuming **every member instantly gains
the level**. Its docstring calls the held-fixed parties a *lower* bound on the benefit.
Under the corrected mechanic that framing is upside down: raising the cap gives nobody
anything until each member individually spends their own resources, so the probe's headline
is not a lower bound at all but a **ceiling**, and a distant one. Left as is, the page would
be quoting a payback period for a purchase that changes no member's stats on the day it
completes.

Re-specify rather than retire — into two honest numbers, plus one genuinely new one that is
better advice than either:

- **`points_gained_immediate = 0.0`, always, by construction.** A cap raise changes nothing
  until members buy in. Saying that plainly is more useful than any payback figure, and it
  is currently the opposite of what the page implies.
- **`points_gained_at_full_adoption`** — the ceiling: recompute with every member *currently
  at the cap* moved up one. Members below the cap gain nothing from a cap raise; they
  already have room. On SC that is 53 of 107 on force, on LI 56 of 105 — so this figure is
  strictly smaller than today's, which moves all 107.
- **`probe_shrine_adoption` — new, and the one worth putting on the page.** The mirror
  question: *what is already unlocked and unbought?* SC's cap is 4 with **54 of 107**
  members below it on force; LI's is 3 with **49 of 105** below. Those members can raise
  their own rate **today, for no guild spend whatsoever**. That is a concrete, actionable
  recommendation of exactly the kind the trials page exists to make, and the model could not
  previously see it because it believed everyone sat at level 1.

`GUILD_SHRINE_LEVELS` survives with a **changed meaning — the guild's cap** — split per
guild (SC force 4 / tempo 4; LI 3 / 3) and derived from the observed per-member maximum. It
feeds the two probes and no longer feeds the rate model; its comment must say so, and must
lose the now-answered open question (§2.2, consequence 2). `guild_shrine_bonuses` survives
for the switched-off path and for `calibrate.py:499`.

### 5.6 Roster-only members ARE admitted — corrected 2026-08-31, during R2

**REVISED.** This section originally argued for `ROSTER_ADMITS_NEW_MEMBERS = False`. Its
central hazard was checked against the live tab and is **false**, and with it gone the
remaining arguments do not carry the decision. The shipped value is
`ROSTER_ADMITS_NEW_MEMBERS = True`.

LI's roster carries five names the manual tab has never heard of: `IronPugs` (id 280884),
`U3` (281111), `auuughhh` (117231), `yiyaa` (287196), `yiyya` (287200).

**The `yiyaa` / `yiyya` rename hazard is void.** The original argument was that the pair
looked like one renamed character, so admitting both would seat one person twice. Measured:
two distinct `characterId`s, and stats that differ — shrines force/tempo 2/3 against 2/2,
Holy Enhancer +5 against +6, C.Smithing 105 against 107. And a duplicate is structurally
impossible: `apps-script/profiles/Code.gs` sets `KEY_COLUMN = 'characterId'` and **upserts**
on it, so a rename updates the row in place. Two rows can only ever mean two characters.
The name-collision guard belongs on the **manual** side of the join, where names are the
only key — not on the roster side, where they are not.

**The upside is not small, and it is now measured.** Both guilds already seat every member
they have: SC's parties are 28 + 24 + 28 + 27 = 107 = its entire roster; LI's are
25 + 24 + 26 + 26 = 101 = its entire roster (R0 manifest,
`research/roster-as-primary-source.md` §1). Neither guild is cap-constrained; both have run
out of *people*. These five are the only additional capacity in existence. Four sit at or
near the LI median in the drawn skills (`auuughhh`: Milking 113 against a median of 112,
Tailoring 113 against 108), and **all five signed up for this week's trials** — R0's own
build log records that it ignored them.

**What an admitted member is, and what they are not.** They are appended to the *merged*
list only, built from roster data alone, in roster-row order after the manual members so the
seed-fixed optimizer trajectory stays reproducible. They do **not** enter the unmerged
`gd.members` that `index.html` renders: that page mirrors the officers' manual tab and must
keep doing so, which is also how an officer notices the row is missing. `top` and `bot` are
necessarily `False` — there is no manual row to read them from and the roster does not carry
body/legs — which understates an admitted member by up to two `ARMOUR_EFFICIENCY_PLUS7`
terms. That is the correct direction: a newcomer is admitted on the evidence we have, not on
the evidence we wish we had. It is commented at the site of the default and counted in
provenance rather than left to be inferred.

The build still prints them, now as a NOTE saying plainly that they were previously dropped,
because the correct long-term fix is still for an officer to add the row.
`ROSTER_ADMITS_NEW_MEMBERS = False` restores the prior "reported, not seated" behaviour
exactly and remains the one-line rollback; both positions are tested.

---

## 6. The switches

All in `src/config.py`, each with the comment style the file already uses (what it does,
what the shipped value is, what the other value restores).

```python
# --- Roster tabs as the primary per-member source ---------------------------
# MASTER SWITCH. False restores the pre-roster build BIT-FOR-BIT: no second gviz
# fetch, no merge, no new data.json keys, no page changes. Pinned by
# tests/test_roster.py::test_roster_disabled_reproduces_the_golden_week.
ROSTER_SOURCE_ENABLED = True

ROSTER_USE_LEVELS = True             # roster skill levels over the manual tab's
ROSTER_USE_HOUSES = True             # roster house levels over the "H" column / DEFAULT_HOUSE_LEVEL
ROSTER_USE_TOOLS = True              # roster tool TIER over the "Tool" checkbox
ROSTER_USE_TOOL_ENHANCEMENT = True   # observed enhancement over the assumed +7.
                                     # False keeps the tier but re-imposes +7 —
                                     # the partial rollback for the −0.52% / −1.26%
                                     # adverse tool slice (§2.3).
ROSTER_USE_SHRINES = True            # each member's OWN purchased shrine levels, in place
                                     # of the guild-wide constant. False restores the
                                     # global GUILD_SHRINE_LEVELS read and the
                                     # once-per-race hoist in simulate_race (§5.4).

ROSTER_ADMITS_NEW_MEMBERS = True     # roster-only names are SEATED, not merely reported.
                                     # False restores "reported, not seated" (§5.6, revised).
ROSTER_MIN_JOIN_RATE = 0.90          # below this the roster is REFUSED for that guild (§9.3)
ROSTER_MAX_AGE_DAYS = 14             # banner threshold, NOT a cutoff (§9.4)
ROSTER_UNKNOWN_TOOL_FATAL = False    # an unmodelled item warns + falls back; True stops the build
TOOL_ENHANCE_WHEN_UNKNOWN = 0        # provisional; see §5.3 and §11.6
```

The five `ROSTER_USE_*` switches are not decoration: they are the **slice harness** that R5
uses to decompose the flip (§7), and afterwards they are the partial-rollback ladder. Note
that `ROSTER_USE_SHRINES` is the only one that also changes a *control-flow* shape — it
removes `simulate_race`'s once-per-race shrine hoist — so its "off" path is the one most
worth pinning with a bit-exactness test (§8.4).

---

## 7. Phases

Each phase is one commit, and each phase's verification is a command whose expected output
is stated.

### R0 — Baseline manifest. No code change.

Before anything is touched, record what today's build produces, at fixed seed, for both
guilds:

```bash
uv run --no-dev python -m src.build 2>&1 | tee /tmp/roster-R0-build.log
cp _site/trials.json  /tmp/R0-sc-trials.json
cp _site/signup.json  /tmp/R0-sc-signup.json
cp _site/li/trials.json /tmp/R0-li-trials.json
cp _site/li/signup.json /tmp/R0-li-signup.json
git rev-parse HEAD > /tmp/R0-baseline-sha
```

Extract, per guild per trial: `tier_reached`, `points`, `credit_points`, `expected_points`,
`slack_fraction`, `clear_probability`; and per guild the four totals. Paste into
`research/roster-as-primary-source.md` §1 as the **BEFORE** table.

**Verification:** the BEFORE table exists and its totals match the CI summary line in the
same log. Nothing else in this plan may be believed without it.

### R1 — `src/roster.py`: fetch, guard, parse. Dead code, fully tested.

**R1.1** `config.ROSTER_TABS = {"sc": "SC Roster", "li": "LI Roster"}` and
`GuildSite.roster_tab` beside `member_tab` (`build.py:103`).

**R1.2** `roster.fetch_roster_csv(tab)` → `scraper.fetch_tab_csv(tab)`. One line. Explicitly
**not** appending `config.GVIZ_NO_HEADER_COLLAPSE`, with a comment saying why (it blanks the
label of every numeric column — the ResearchPack verified this).

**R1.3** `config.ROSTER_COLUMNS` — one table, the single source of truth for both the parser
and the guard, keyed by `config.SKILLS` so the two can never drift:

| `config.SKILLS` | level col | house col | tool col | tool-enh col |
|---|---|---|---|---|
| Milking | `milking` | `house_dairy_barn` | `tool_milking` | `tool_milkingEnh` |
| Foraging | `foraging` | `house_garden` | `tool_foraging` | `tool_foragingEnh` |
| Woodcutting | `woodcutting` | `house_log_shed` | `tool_woodcutting` | `tool_woodcuttingEnh` |
| C.Smithing | `cheesesmithing` | `house_forge` | `tool_cheesesmithing` | `tool_cheesesmithingEnh` |
| Crafting | `crafting` | `house_workshop` | `tool_crafting` | `tool_craftingEnh` |
| Tailoring | `tailoring` | `house_sewing_parlor` | `tool_tailoring` | `tool_tailoringEnh` |
| Cooking | `cooking` | `house_kitchen` | `tool_cooking` | `tool_cookingEnh` |
| Brewing | `brewing` | `house_brewery` | `tool_brewing` | `tool_brewingEnh` |
| Bell Farming | `alchemy` | `house_laboratory` | `tool_alchemy` | `tool_alchemyEnh` |
| Enhancing | `enhancing` | `house_observatory` | `tool_enhancing` | `tool_enhancingEnh` |

Plus the singletons `name`, `characterId`, `capturedAt`, `revision`,
`shrine_force_skilling`, `shrine_tempo_skilling`.

Note the two traps this table defuses in one place: "Bell Farming" ↔ `alchemy` (the guild's
in-joke column, which `config.TRIAL_SKILL_TO_SHEET_COLUMN` already handles for the manual
tab) and "C.Smithing" ↔ `cheesesmithing`.

**R1.4** `roster._validate_header(header)` — builds `{name: index}` and requires **every**
name in `ROSTER_COLUMNS` to be present, by exact match. Raises `SheetStructureError` listing
every missing name, in the message style `scraper._validate_gviz_header` uses. Extra columns
are allowed (the `stableGear` toggle adds 14 and must not break the build).

**R1.5** `roster.parse(csv_text) -> list[RosterRow]`. `RosterRow` is a plain dataclass:
`name`, `character_id`, `captured_at`, `levels: dict[str, Optional[int]]`,
`houses: dict[str, Optional[int]]`, `tools: dict[str, Optional[str]]`,
`tool_enh: dict[str, Optional[int]]`, `shrine_force`, `shrine_tempo` — all keyed by
`config.SKILLS` name, all `Optional`, blank preserved as `None` and `"0"` as `0`. A dedicated
`_to_int_strict` is needed: `reader._to_int` returns `None` for both blank and garbage, which
would erase the blank/zero distinction the ResearchPack insists on. It must return `None`
for blank, the int for a numeral, and **raise** for anything else — a non-numeric level cell
on a machine-written tab is a structure problem, not a stray officer keystroke.

**Verification:** `uv run python -m pytest tests/test_roster.py -v` passes; `git grep -n
roster src/build.py` returns nothing (the module is not yet wired). One live smoke run:

```bash
uv run python -c "from src import roster, config; \
  rows = roster.parse(roster.fetch_roster_csv(config.ROSTER_TABS['sc'])); \
  print(len(rows), rows[0].name, rows[0].captured_at)"
```
Expect `107 <name> 2026-08-28…`.

### R2 — Join and merge, plumbed in, gated OFF.

**R2.1** `SkillEntry` / `MemberRow` gain the optional fields (§5.2); `scraper.to_dict` gains
the key filter.

**R2.2** `roster.join(members, rows) -> JoinReport`. Reuses `signup._norm_name`
(casefold + collapsed whitespace) — promote it to a shared helper in `reader.py` and have
`signup.py` import it, rather than copying it; two normalisers that drift is exactly the bug
this join exists to avoid. The ambiguity rule is `signup.py:1253-1259`'s, verbatim: a
normalised key held by two members on either side matches **nobody**. `JoinReport` carries
`matched: dict[member_index, RosterRow]`, `normalized_matches: list[str]`,
`unmatched_members: list[str]`, `unmatched_roster: list[str]`, `ambiguous: list[str]`.

**R2.3** `roster.merge(members, report) -> tuple[list[MemberRow], Provenance]`. Returns a
**deep copy**; `gd.members` is never mutated (§ Summary: the register must keep mirroring the
manual tab). Per member, per skill, per field:

```
level  := roster.levels[skill]  if ROSTER_USE_LEVELS  and not None  else manual level
house  := roster.houses[skill]  if ROSTER_USE_HOUSES  and not None  else manual "H"  (else DEFAULT_HOUSE_LEVEL, downstream)
tool_item, tool_enhance := roster values if ROSTER_USE_TOOLS and item not None else (None, None)
top, bot := manual, always
```

and a provenance tag per `(member, skill, field)`, aggregated into per-guild counters.

**R2.3b — admission (§5.6).** Under `ROSTER_ADMITS_NEW_MEMBERS`, every roster row that
matched no member becomes a new `MemberRow` built from roster data alone and **appended to
the merged list, in roster-row order, after every manual member**. Order is not cosmetic:
the optimizer's search is seeded, and its trajectory depends on the member list's order, so
"appended in source order" is what makes the build reproducible.

Four properties of an admitted member, each of which needs stating because each is a place
the implementation could plausibly do something else:

- **They exist in the merged list only.** `gd.members` — the unmerged list that `process()`
  turns into `index.html` — never sees them. That page mirrors the officers' manual tab and
  must keep doing so; it is also how an officer notices the row is missing. The consequence
  is a deliberate discrepancy — `index.html` says 101 while `trials.html` says 106 — which
  the provenance strip (R4.1) must name outright, because an unexplained one reads as a bug.
- **`top` and `bot` are necessarily `False`.** There is no manual row to read them from and
  the roster does not carry body/legs (permanently — §11.3). This understates an admitted
  member by up to two `ARMOUR_EFFICIENCY_PLUS7` terms, i.e. `0.2364` of efficiency. That is
  the correct direction — a newcomer is admitted on the evidence held, not the evidence
  wished for — but it is **not** a harmless conservatism here (§9, Risk 10), and it must be
  visible in provenance rather than inferred from an absence.
- **Manual-only members are kept, not dropped.** The mirror-image case: LI's manual tab holds
  one member (`OTZ`) the roster has never seen. The merge iterates over the manual list and
  *enriches* it, so this is automatic rather than engineered — but it is exactly the kind of
  property that a later "rewrite the merge as a roster-driven loop" would silently break, so
  §8.3 pins it.
- **No member is counted twice.** A member on both tabs is enriched in place, never appended.

**R2.4** `build._fetch_guild`: after `gd = scrape_member_tab(...)`, and **only when
`config.ROSTER_SOURCE_ENABLED`**, fetch + parse + join + merge; put the merged list on
`_GuildInputs.members` and the *unmerged* `gd.members` into `process()` for the register.
Carry `roster_provenance` and `roster_unavailable: str` on `_GuildInputs`. Print the join
NOTE/WARNING pair beside the existing sign-up ones.

Gating at the **fetch** rather than at the consumers is deliberate: with the switch off the
build does not even talk to the roster tab, so the rollback also covers the case where the
Apps Script deployment is the thing that is broken.

**Verification:** with `ROSTER_SOURCE_ENABLED = False`, a full build produces `_site/`
byte-identical to R0 (`diff -r`); with it `True` in a scratch run, the log prints join
counts matching the ResearchPack's measured 107/107 and 100/101, and — with
`ROSTER_ADMITS_NEW_MEMBERS = True` — LI's merged member count reads **106** (101 manual,
of which 100 matched, plus 5 admitted) while SC's reads **107** unchanged.

### R3 — The tool table, per-member shrines, and `member_bonuses`. Still gated OFF.

**R3.1** Generate `config.TOOL_STATS` and `config.ENHANCEMENT_MULT_TABLE` from
`research/item-stats.json`; keep `TOOL_SPEED_*_PLUS7` / `TOOL_SUCCESS_*_PLUS7` in place.

**R3.2** `trials._resolve_tool(member, skill) -> tuple[Optional[str], Optional[int]]` — the
sibling resolver. `_resolve_level_and_checks` keeps its 5-tuple; `calibrate.py:369` unpacks
it and must not be broken by a signature change made for convenience.

**R3.3** `trials.tool_bonus(skill, item, enhance) -> Optional[tuple[float, float]]` returning
`(speed, success)`; `None` for an item not in the table. Raises on a slot mismatch (§5.3).

**R3.4** The precedence ladder inside `member_bonuses`, replacing the two `if tool` branches.

**R3.5 — per-member shrines (§5.4).** `MemberRow.shrine_levels` populated at merge time;
`trials.member_shrine_bonuses(member, overrides=None)` dispatching on the existing
`GUILD_SHRINE_SKILLING_BUFFS` channel table; the two-way resolve in `member_bonuses`; and
the removal of the once-per-race hoist at `simulate_race:1198` (and `:771`, `:855`) under
`ROSTER_USE_SHRINES`. **`MemberBonuses.shrine_speed` / `.shrine_efficiency` keep their
fields and keep being applied at the point of use in `_prepare_member` — only their
population changes.** Nothing is folded into `b.speed` / `b.efficiency`.

**Verification:** `pytest tests/test_trials.py -v` — all ~90 existing tests pass untouched
(the identity asserts in §5.3 and the switched-off shrine path are why; note
`test_trials.py:159, 504, 530, 766-790, 811` all exercise `guild_shrine_bonuses` directly
and must remain green *unmodified*). New tests in §8.3–§8.4 pass. `pytest tests/ -v` green.

### R4 — Provenance on the pages and in the JSON. Renders "manual" for everything while OFF.

Landing this **before** the flip is the point: nothing may ship with better numbers than the
page admits to.

**R4.1** A per-guild **data-provenance strip** on `trials.html` and `signup.html`, beside the
buff-slider strip and styled the same way:

> **Member data** — 107 members. 98 roster-backed, captured 2026-08-28 (3 days ago).
> 9 members hide their gear → tools from the *SC Member Data* tab. 0 unmodelled tool items.
> 5 roster names not on the member tab (not seated).

Outlined and captioned when `capturedAt` is older than `ROSTER_MAX_AGE_DAYS`, exactly as the
buff strip is outlined off the published level.

**R4.2** Per-member marks in every roster table (`build.py:621`, `:2716`) and in the sign-up
enforced/recommended lists: a filled mark for roster-backed, hollow for manual, and the tool
badge upgraded from a binary `Tool` to the actual tier and enhancement (`Cel +9`), muted
when it came from the checkbox and outlined when the item is unmodelled.

This is the single highest-information change on the page and it costs one badge helper: it
turns "this member has a tool" into "this member has a Rainbow Chisel at +4", which is the
fact that moves their rank.

**R4.3** A `provenance` block in `trials.json`, `signup.json` and `data.json`:
`{roster_backed, manual_backed, captured_at, age_days, gear_hidden, unknown_tools,
unmatched_roster, unmatched_members, normalized_matches}`.

**R4.4** **Edit** — not append to — the `Assumptions & caveats` block (`build.py:2115`) and
the sigma sentence (`:3276`). Two of the caveats there become false for roster-backed
members ("+7 on every piece"; "blank H → 4"). This repo's own doctrine, argued at length in
`src/draw.py`'s docstring, is that a stale caption is worse than none.

**Verification:** build with the switch off — the strip renders "0 roster-backed, source:
manual tab" and every mark is hollow; `diff` against R0 shows changes confined to the new
strip and the badges. Build with it on in a scratch run — the counts match R2's log.

### R5 — The flip, in four measured slices. **This is the phase that changes numbers.**

Run **six** builds, at the fixed seed, recording the full manifest each time —
`ROSTER_ADMITS_NEW_MEMBERS = False` throughout runs 0–4, then run 5 for admission alone (see
below for why it is deliberately outside the band framework). The bands are
§2.3's measured means, which came from `trials._prepare_member` / `trials.success` over
every matched member × skill:

| run | switches | band (SC / LI mean Δrate) | why it points that way |
|---|---|---|---|
| 0 | `ROSTER_SOURCE_ENABLED=False` | = R0 exactly | the golden check, live |
| 1 | `+USE_LEVELS` | **+2.41% / +6.57%** | manual levels understate: LI `{+1:327, +2:142, +3:44, +4:10, …+17:1}` |
| 2 | `+USE_HOUSES` | **+0.03% / −0.16%** | 59 of 88 LI cells blank at an assumed 4 against a measured ~3.1; SC records all of its |
| 3 | `+USE_SHRINES` | **+1.33% / +0.89%** | modelled at a flat 1 against means of 2.99 / 2.30 (§2.2) |
| 4 | `+USE_TOOL_ENHANCEMENT` (tier lands with it) | **−0.52% / −1.26%** | observed enhancement against the assumed `+7` |
| all | everything on | **+3.30% / +6.00%** | the joint run; the residual vs the sum is the interaction term |

Slice 3 subsumes what an earlier draft of this plan scheduled as a separate late phase; §5.4
says why it moved. Slice 4 folds `USE_TOOLS` in with `USE_TOOL_ENHANCEMENT` because the tier
change alone is ~flat (the checkbox is 97% faithful) — run it separately anyway if slice 4
misses its band, to localise the fault.

**The reconciliation is the verification, and it is falsifiable.** Each slice's mean
per-member rate change, computed over every matched member × **drawn** skill, must land
within **±0.1pp** of its band. The bands above were measured at tier 11 over all ten skills
while a build races the week's actual four, so the band is re-derived per draw by re-running
the §2.3 measurement restricted to those four skills — *before* the build, not after.
**If a slice misses its band the implementation is wrong and the phase does not ship. Do not
adjust the band**: it comes from an independent measurement, and a disagreement means one of
the two is wrong, which is exactly what this step exists to detect.

**Why this matters more now that the totals go UP.** A number that falls invites scrutiny; a
number that rises does not. Three of the four slices are favourable, so without per-slice
bands this change would land as an unexamined 3–6% improvement that nobody checked. Two
specific properties are therefore load-bearing:

- **Slice 4 must come out negative**, at roughly the stated magnitude. It is the only adverse
  term, and it is the evidence that the change is a *correction* rather than a uniform coat
  of optimism. A slice 4 that came out positive, or near zero, would mean the enhancement
  repricing is not actually being applied.
- **The interaction residual must stay small** (§2.3 measures it at 0.05pp SC, 0.04pp LI). A
  large residual means one slice is not doing what its name says — most likely a switch that
  silently gates more than it claims.

**Admission is NOT a fifth slice, and it must not be folded into the four.** This is a
decision, so here is the reasoning. Slices 1–4 are *rate* errors, each measured as a mean
Δrate over **matched members × drawn skills**. Admission changes no matched member's rate; it
changes the party composition and, fatally for the arithmetic, it changes the denominator —
the five admitted members are by definition not in the population the bands were measured
over. Expressing "five more members" as a mean Δrate over a set that excludes them is not a
harder measurement, it is a different one. Worse, changing the denominator midway through the
table is precisely the mechanism that manufactures a spurious interaction residual, which is
the signal §2.3 asks us to trust.

So `ROSTER_ADMITS_NEW_MEMBERS = False` is held throughout runs 1–4, keeping the four bands
comparable to the §2.3 measurement that produced them, and admission gets **run 5 with its
own, different verification** — a composition check, not a Δrate band:

| check | expectation |
|---|---|
| SC merged member count | **107, unchanged** — SC's roster and manual tab both hold 107 and all 107 match, so SC admits nobody |
| **SC run 5 vs run 4** | **byte-identical.** A free and strong control: the admission path must not leak into a guild it has no business touching |
| LI merged member count | **101 → 106** |
| LI sign-up WARNING | the `5 sign-up name(s) match NO member … IronPugs, U3, auuughhh, yiyaa, yiyya` line **disappears** |
| LI enforced sign-ups | rises by up to 5 — all five volunteered, so `signup.py` now matches them where it previously ignored them |
| LI seats used | 101 → **104** (see below) |

**And run 5 flips LI into a regime it has never been in.** LI's cap is 26 a party, so
4 × 26 = **104 seats** against a roster that becomes **106**. Today LI seats every member it
has; after admission it cannot, and for the first time **LI's bench is a real decision rather
than an artefact of having run out of people**. SC stays member-constrained (107 against
4 × 28 = 112). That asymmetry is the most interesting thing run 5 produces and it belongs in
the write-up, not just the manifest.

Note the second-order consequence, which is why Risk 10 exists: the two members LI now has to
bench are chosen by the optimizer on modelled rate, and admitted members are systematically
understated by their missing `top`/`bot`. The population most likely to be benched is exactly
the population whose numbers are least complete.

Record all seven manifests, the four deltas, the interaction residual, run 5's composition
table, and the tier table before and after in `research/roster-as-primary-source.md` §2; put
the headline in the CI summary line so the change is legible in the deploy log rather than
only in a file.

**Verification:** the reconciliation above, plus `pytest tests/ -v` green, plus the tier
table before/after. Tiers are now expected to be **gained**, particularly on LI where the
combined slice is +6.00%; any tier that is *lost* is a surprise and must be explained rather
than absorbed.

### R6 — Recalibrate `RISK_SIGMA_SYSTEMATIC`. Mandatory, and its own commit.

`calibrate.py` prices `augment=±3 per slot` (`:272`), `tool_flip=0.03` (`:273`) and
`house_blank` (`:264`) as **uncertainty**. All three are now **observed** for roster-backed
members. Leaving `RISK_SIGMA_SYSTEMATIC = 0.0131` keeps a pessimism that is now knowingly
false, and `expected_credit_points` — the shipped objective — would under-reach as a result.
Cutting it by hand would substitute a guess for a measurement. Neither is acceptable, so the
campaign is re-run.

**R6.1** `Sources.respect_provenance: bool = False`. When `True`, `_prepare_perturbed` skips
`augment` and `tool_flip` for a member+skill whose tool is roster-backed, and skips
`house_blank` resampling for a roster-backed house. Per-member-provenance, not a global
switch, because the gear-hiders keep every one of those uncertainties and must keep paying
for them.

**R6.2** Re-run `DEFAULT` with `respect_provenance=True` on the post-merge live rosters.
Publish the **full ablation table**, not just the number.

**R6.3** Set `RISK_SIGMA_SYSTEMATIC` to the measured value, keeping `0.0131` and its
derivation in the comment above it, in the style that constant already uses.

**Prediction, to be recorded before the run and checked against it:** sigma **shrinks but
does not vanish**. The unmodelled neck / ring / earring gear (`gear_speed`,
`gear_efficiency`, `gear_gathering`) is untouched by this change — the roster does not carry
those slots unless the upstream `stableGear` toggle is switched on (§11.2) — so that term
survives in full and it is not the small one.

**R6.4 — and this is the trap, which the corrected direction makes worse rather than
better.** R5 makes parties *faster* and R6 makes the risk discount *smaller*, so
`expected_points` now moves the **same** way in both phases. The first draft of this plan
worried they would cancel and hide a bug; the truth is the opposite and more dangerous —
they compound, so a bug in either is camouflaged by a plausibly-large favourable move rather
than contradicted by one. They are therefore separate commits with separate manifests, and
the write-up reports the two deltas separately even though only their sum ships. R6's delta
must appear in `expected_points` and `clear_probability` **and nowhere else** except where
the optimizer re-seats as a consequence; a change in the deterministic `credit_points`
between R5 and R6 would mean the recalibration has leaked into the rate model, which it must
never do.

**Verification:** the ablation table is in `research/`; `RISK_SIGMA_SYSTEMATIC`'s new value
is traceable to a row in it; the R6 manifest differs from R5's only in `expected_points`,
`clear_probability` and whatever the optimizer re-seats as a result.

### R7 — The shrine probes, and the cap.

The shrine **rate** correction shipped in R3/R5, because it is a correctness fix. What stays
here is the **advice** layer: it changes no rate, it depends on the corrected model already
being in place, and it is page work. That is the sequencing justification — implementation
early because it is wrong for 88–95% of members, presentation late because it is
presentation.

**R7.1** Split `config.GUILD_SHRINE_LEVELS` **per guild** and re-point its meaning at the
guild's **cap** (SC force 4 / tempo 4; LI 3 / 3), derived from the observed per-member
maximum on each roster. Its comment must state the corrected mechanic and must **delete the
now-answered open question** at `config.py:1136-1141` — a settled question left sitting in
config reads as an open one, and the next person to touch shrines will re-derive it.

**R7.2** Re-specify `probe_shrine_upgrade` per §5.5: `points_gained_immediate = 0.0` by
construction, and `points_gained_at_full_adoption` computed by moving only the members
*currently at the cap* up one level. Delete the `config.GUILD_SHRINE_LEVELS` rebinding
trick in `week_total` — under per-member shrines it no longer expresses the hypothetical it
was written for — and replace it with per-member level overrides threaded into
`member_shrine_bonuses`. Update `ShrineUpgrade`'s docstring, which currently argues at
length for a lower-bound reading that the corrected mechanic inverts.

**R7.3** Add `probe_shrine_adoption` — the headroom probe (§5.5): how many members sit below
their guild's cap, and what closing that gap is worth in credit points, at **zero guild
spend**. Publish it in the trials page's shrine section, above the upgrade probe, because it
is the more actionable of the two by a wide margin.

**Verification:** `probe_shrine_upgrade` returns `points_gained_immediate == 0.0` for every
shrine on both guilds (a test, not an observation); `probe_shrine_adoption`'s member counts
match §2.2's distributions (SC 54 of 107 below cap on force, LI 49 of 105); the page renders
both and `pytest tests/ -v` is green.

### R8 — README and the research note.

`README.md` gains a "Where member data comes from" subsection: the three-tier precedence
stated plainly, the switch ladder, the four-slice table, and the measured before/after
totals — including the point that the totals **rose**, that three of four terms are
favourable and one is not, and that the adverse one is the evidence the change is a
correction. The shrine mechanic (cap vs purchase) belongs there too: it is the kind of thing
this README already explains once and well, and it is the reason a reader will otherwise
misread `GUILD_SHRINE_LEVELS`.

---

## 8. Test plan

### 8.1 The golden test — the rollback's proof

```python
def test_roster_disabled_reproduces_the_golden_week(monkeypatch):
    """ROSTER_SOURCE_ENABLED = False must reproduce the pre-roster week EXACTLY."""
```

A checked-in `tests/golden/week_pre_roster.json`, generated at R0 from `trials.run_week` on
a fixed synthetic 30-member roster with a fixed seed and a fixed draw, compared with `==`
against `WeekResult.to_dict()` under the switch off. Not `approx`: `_prepare_member`'s
docstring records a live case where a one-ULP change reshuffled every SC party for no gain,
so ULP-exactness *is* the property under test.

Two companions:

```python
def test_data_json_is_byte_identical_with_roster_off()      # the to_dict key filter
def test_roster_disabled_makes_no_second_http_request()     # gating is at the FETCH
```

### 8.2 Parsing and the structure guard (`tests/test_roster.py`)

Fixtures in the style of `tests/test_scraper.py`: a `_roster_header()` helper emitting the
78 named columns, and `_roster_row(**overrides)`.

- `test_header_guard_accepts_the_live_column_set`
- `test_header_guard_rejects_a_renamed_column` — every missing name listed in the message
- `test_header_guard_rejects_a_missing_column`
- `test_header_guard_tolerates_extra_columns` — the `stableGear` 14 must not break it
- `test_columns_are_read_by_name_not_position` — **shuffle the entire tool block**, assert an
  identical parse. This is the ResearchPack's named hazard, pinned.
- `test_tool_slot_mismatch_is_a_structure_error` — "Celestial Spatula" under `tool_milking`
- `test_blank_and_zero_are_distinguished` — `""` → `None`, `"0"` → `0`, on a level, a house,
  and an enhancement
- `test_non_numeric_level_raises_rather_than_becoming_none`
- `test_alchemy_column_maps_to_bell_farming`
- `test_cheesesmithing_column_maps_to_c_smithing`
- `test_gviz_no_header_collapse_is_not_appended` — asserts the fetched URL

### 8.3 The join and the merge

- `test_join_is_case_insensitive` — `dome`/`Dome`, `VIadd`/`Viadd`, `FeaI`/`Feai`
- `test_join_reports_unmatched_on_both_sides`
- `test_ambiguous_normalised_name_joins_to_nobody` — mirrors `signup.py:1253-1259`
- **`test_gear_hider_keeps_roster_levels_and_manual_tools`** — *the* per-field test: a member
  with populated levels/houses/shrines and 20 blank tool columns gets roster levels, roster
  houses, and the manual checkbox's tool
- `test_roster_only_members_are_admitted_by_default` — all five live-shaped names, five
  distinct `characterId`s
- `test_the_yiyaa_yiyya_pair_is_two_members_not_one` — both admitted, not deduplicated
- `test_an_admitted_member_has_no_top_or_bot` — `False` for both, necessarily (§5.6)
- `test_an_admitted_member_is_absent_from_the_unmerged_register_list`
- `test_admitting_is_deterministic_in_roster_row_order`
- `test_roster_only_member_is_reported_but_not_seated_when_the_switch_is_off`
- `test_a_member_on_both_tabs_is_never_admitted_twice`
- `test_member_missing_from_the_roster_is_fully_manual` — the `OTZ` mirror-image case: the
  manual tab knows one LI member the roster has never seen, and the merge must keep them
  (§11.9). Automatic today because the merge *enriches* a manual list; pinned because a later
  rewrite as a roster-driven loop would silently drop them.
- `test_merge_does_not_mutate_the_input_members` — the register must keep mirroring the sheet
- `test_join_below_min_rate_refuses_the_roster_for_that_guild`
- `test_provenance_counts_sum_to_member_count_times_skill_count`

### 8.4 Tools and shrines (`tests/test_trials.py` additions)

- `test_tool_table_reproduces_the_four_shipped_constants_at_plus7` — exact `==` (§5.3)
- `test_tool_table_matches_item_stats_json` — regenerate and compare; the pinning test
- `test_tool_table_carries_no_loot_or_xp_stats` — no `RareFind` / `Experience` keys
- `test_rainbow_tool_is_priced_between_burble_and_holy` — a tier the checkbox cannot express
- `test_enhancing_tool_feeds_success_not_speed` — at every tier in the table
- `test_enhancement_level_zero_is_the_base_stat`
- `test_enhancement_level_is_clamped_to_the_table`
- `test_unknown_tool_item_falls_back_to_the_checkbox_and_is_counted`
- `test_unknown_tool_item_is_fatal_when_the_switch_says_so`
- `test_blank_enhancement_uses_the_configured_default_and_is_counted`
- `test_member_bonuses_is_unchanged_when_the_skill_entry_has_no_roster_fields` — exact `==`
  against the pre-change value; this is what lets the ~90 existing bonus tests stand

**Shrines (§5.4–§5.5).** The bit-exactness cases come first because they are what protects
the optimizer's trajectory:

- `test_shrines_off_is_bit_identical_to_the_hoisted_path` — exact `==` on the full
  `simulate_race` result with `ROSTER_USE_SHRINES = False`, proving that removing the
  once-per-race hoist under the switch changed nothing under it
- `test_shrine_bonuses_stay_out_of_member_speed_and_efficiency` — `MemberBonuses.speed` and
  `.efficiency` still report only what the member *owns*; the shrine terms are still in
  their own two fields. This is the test that catches a well-meaning fold.
- `test_prepare_member_addition_order_is_preserved` — exact `==` against a hand-computed
  `floor(work_power(level, eff + shrine_eff))` and `action_seconds(skill, speed + shrine_speed)`
- `test_member_shrine_bonuses_uses_the_members_own_level`
- `test_only_force_and_tempo_reach_the_race_per_member` — the per-member twin of the existing
  `test_only_force_and_tempo_shrines_reach_the_tier_race`; Rarity, Spirit and Scholar are on
  the roster with non-zero values and must contribute exactly 0.0
- `test_member_shrine_level_zero_lowers_the_rate_against_the_modelled_one` — the 5 SC / 10 LI
  members the current model *overstates*
- `test_shrine_levels_clamped_to_the_max`
- `test_shrine_buffs_apply_in_trials_false_zeroes_the_per_member_path_too`
- `test_blank_shrine_column_falls_back_to_the_guild_map`
- `test_probe_shrine_upgrade_immediate_gain_is_zero` — by construction, both guilds, every shrine
- `test_probe_shrine_upgrade_moves_only_members_at_the_cap`
- `test_probe_shrine_adoption_counts_members_below_the_cap`

### 8.5 Existing tests

**None should need changing.** Every new dataclass field is defaulted, every new code path is
gated, and the four identity asserts make the tool refactor a no-op at `+7`. If a test in
`test_trials.py`, `test_scraper.py`, `test_reader.py`, `test_optimizer.py` or `test_signup.py`
needs an edit, that is a signal the change is not as surgical as claimed — stop and
re-examine rather than editing the test.

### 8.6 Live harness (not pytest)

`research/roster-as-primary-source.md` records the five-slice run of R5 and the R6 ablation.
Both need the network and neither belongs in the offline suite, which is the same line
`research/partial-tier-credit.md` §9 already draws.

---

## 9. Risks and mitigations

### Risk 1 — a silent column remap scores the wrong tool
**Probability:** medium (the ResearchPack states the order varies upstream). **Impact:** high
— plausible-looking numbers, no error.
**Mitigation:** three independent layers. (a) read by header name; (b) the guard demands
every expected name, so a rename fails loudly; (c) the **slot cross-check** (§5.3) catches
the case a name lookup cannot — a header row shifted relative to its data. Layer (c) is the
one that matters, because (a) and (b) both succeed in that scenario.

### Risk 2 — the separate Apps Script deployment changes its header and stops the deploy
**Probability:** medium — it is a *different* deployment whose header shifts when a module
toggle moves, and nobody who moves that toggle is thinking about this pipeline.
**Impact:** SC is `required=True`, so an uncaught `SheetStructureError` out of the roster
fetch kills **every page of both guilds**.
**Mitigation:** the roster fetch is wrapped in `_fetch_guild` and **degrades**: catch
`SheetStructureError`, set `roster_unavailable`, warn loudly, render the banner, and build
from the manual tab.

This is the same trade `_load_draw` makes, and it is worth stating why the counter-example
does not apply. INCIDENT 2026-08-14 showed a quiet fallback shipping *wrong advice* — the
site optimised `TRIAL_SKILLS_CURRENT`, a stale constant, behind a banner. Here the fallback
is not a stale constant, it is **today's shipped behaviour**: the status quo ante, already
believed good enough to publish this morning. Degrading to it is strictly better than
degrading to nothing, and the banner says which source produced the page. A network
`RuntimeError` still propagates and fails the build, exactly as elsewhere.

### Risk 3 — the join silently loses a strong member, or mis-joins wholesale
**Probability:** low for one member (measured: 1 of 101 on LI); very low but catastrophic for
a wholesale mis-join (gviz serving a different tab past the guard).
**Impact:** one lost member is harmless — they keep 100% manual data, i.e. today's
behaviour. A wholesale mis-join would silently reprice the entire guild.
**Mitigation:** both sides reported every build; and `ROSTER_MIN_JOIN_RATE = 0.90` — if fewer
than 90% of the manual tab's members join, the roster is **refused for that guild** with a
loud warning. Measured headroom: SC joins at 100%, LI at 99%.

### Risk 4 — the totals RISE and nobody audits them
**Probability:** certain (SC +3.30%, LI +6.00%). **Impact:** high, and higher than the
falling case this risk originally described. A number that drops gets challenged; a number
that jumps 6% in the guild's favour gets accepted, and a bug that inflates rates is then
indistinguishable from the correction it is hiding inside. The failure mode is an officer
planning against tiers the guild cannot actually reach.
**Mitigation:** §7 R5's **per-slice** bands with the falsifiable `±0.1pp` reconciliation —
applied to the three favourable slices as strictly as to the adverse one; the requirement
that slice 4 come out **negative**, which is the specific evidence against uniform
optimism; the interaction-residual check; and the R6 separation (Risk 6), which now matters
more because R5 and R6 push the same way rather than opposite ways. The CI summary line
carries the four deltas, not just the total.

### Risk 5 — sigma is left stale, or cut without measuring
**Probability:** high if R6 is treated as optional. **Impact:** high — `RISK_SIGMA_SYSTEMATIC`
feeds `expected_credit_points`, which is the shipped objective. A now-false pessimism makes
the optimizer under-reach on every trial of every week.
**Mitigation:** R6 is a mandatory phase with a gate: the new value must be traceable to a row
in a published ablation table. Not a judgement call, not a round number.

### Risk 6 — R5 and R6 compound and camouflage a bug in either
**Probability:** medium-high — corrected as of §7 R6.4: they move `expected_points` the
**same** way, not opposite ways. **Impact:** high, because a large favourable move is exactly
what a bug in either phase would also produce, so the result looks confirmatory rather than
suspicious.
**Mitigation:** separate commits, separate manifests, both deltas reported even though only
the sum ships; and the invariant that R6 must not move deterministic `credit_points` at all
— if it does, the recalibration has leaked into the rate model. §7 R6.4.

### Risk 6b — the shrine fold, or the lost hoist
**Probability:** medium — both are the natural thing for an implementer to do.
**Impact:** high and silent. Folding shrines into `b.speed` / `b.efficiency` re-associates
arithmetic that `_prepare_member`'s docstring records as having reshuffled every SC party
for a one-ULP change; forgetting to remove the once-per-race hoist would give every member
the *first* member's shrine levels, which is wrong in a way that produces entirely plausible
numbers.
**Mitigation:** three exact-`==` tests (§8.4): the switched-off bit-identity, the
"shrines stay out of speed/efficiency" assertion, and the addition-order check. Note the
second one is only meaningful because `MemberBonuses` deliberately keeps the fields separate
— a design choice made for an unrelated reason that now pays for itself.

### Risk 10 — admitted members are understated, and LI must now bench somebody
**Probability:** certain. **Impact:** medium, and sharper than it first appears.
An admitted member has no manual row, so `top` and `bot` are `False` and their efficiency is
understated by up to `0.2364`. Simultaneously, admission takes LI from 101 members in 104
seats to **106 in 104** — so LI acquires a binding cap for the first time and the optimizer
must bench two. The population most likely to be benched is precisely the population whose
data is least complete: that is a bias with a mechanism, not a coincidence.
**Mitigation:** the direction is stated and defended (admit on the evidence held, not the
evidence wished for); it is counted in provenance and captioned on the page rather than left
to be inferred; and the standing NOTE tells officers that adding the row to the manual tab is
what supplies the missing `top`/`bot`. **The measurement to record at R5 run 5 is which
members LI benches** — if both are admitted ones, that is a result to report rather than
accept quietly. Note also that the understatement makes any reported tier gain a **floor**.

### Risk 11 — admission silently contaminates the four slice bands
**Probability:** high if not explicitly prevented; leaving the switch on is the natural thing
to do. **Impact:** high — the slices would be measured over one population and compared
against bands derived from another, and the mismatch would surface as a fake interaction
residual, discrediting the one check that would otherwise have caught it.
**Mitigation:** `ROSTER_ADMITS_NEW_MEMBERS = False` is pinned off for runs 0–4; admission gets
its own run with a composition check instead of a Δrate band (§7 R5). SC's run 5 being
byte-identical to its run 4 is the control that proves the isolation held.

### Risk 12 — admission changes the SIGN-UP plan, not just the trials page
**Probability:** certain — all five volunteered, and R0's log records `signup.py` ignoring
them. **Impact:** medium, and easy to miss because the four slices are all trials-page
measurements.
`signup.py` matches sign-up names against the member list, so five names that previously
matched nothing now match, arrive as **enforced** volunteers, and are locked into the trials
they ticked (they are never moved or benched — `README.md`, sign-up rule 1). That is a
second, independent behaviour change riding on the same switch: LI's enforced plan gains up
to five locked seats it did not have.
**Mitigation:** R5 run 5's composition table covers `signup.json` as well as `trials.json`;
the disappearance of the `5 sign-up name(s) match NO member` WARNING is the crisp signal that
it took effect; and the enforced-seat count is recorded before and after. Note the
interaction with Risk 10: an enforced member cannot be benched, so an *understated* admitted
member who volunteered is locked in regardless — which is, for once, the failure mode
pointing the harmless way.

### Risk 7 — `TOOL_ENHANCE_WHEN_UNKNOWN = 0` understates a non-trivial population
**Probability:** unknown, and that is the problem. **Impact:** proportional to the count.
**Mitigation:** counted and printed every build, with a numeric trigger: above 5% of matched
member-skills on either guild, resolve before R5 rather than after (§11.6).

### Risk 8 — `data.json` grows keys and breaks a downstream consumer
**Probability:** low (the only known consumer is this repo's own pages).
**Mitigation:** additive keys only; omitted entirely when the switch is off; pinned by
`test_data_json_is_byte_identical_with_roster_off`.

### Risk 9 — build time
**Probability:** low. **Impact:** low.
**Mitigation:** priced rather than hoped. One extra gviz GET per guild (~1s, in the parent
alongside the existing fetches) and one O(members × skills) merge — call it 1,070 field
resolutions per guild, microseconds. **Zero** added work inside `_prepare_member` or
`simulate_race`, so the ~5m34s optimise phase is untouched. **Verification:** the per-unit
timing table in the README's "Where the run time goes" is re-measured at R5 and must not
move outside noise.

### If implementation gets stuck

1. Check the failing value against the ResearchPack's measured tables first — several of
   them (the enhancement distribution, the tick/tier cross-tab, the join counts) are direct
   assertions about what a correct implementation must see.
2. If a *phase* fails, revert that phase alone; the commit-per-phase structure is what makes
   that possible.
3. If the reconciliation in R5 misses its band, **do not adjust the band**. The band comes
   from an independent measurement; missing it means the code disagrees with a measurement,
   and one of the two is wrong.
4. Three failed attempts at the same step: stop, report what was tried, and leave the
   switches off.

---

## 10. Rollback

A ladder, cheapest first. Every rung is one line in `config.py`.

| rung | switch | restores |
|---|---|---|
| 1 | `ROSTER_SOURCE_ENABLED = False` | today's build **bit-for-bit** — no fetch, no merge, no JSON keys, no page change. Pinned by the golden test. |
| 2 | `ROSTER_USE_TOOL_ENHANCEMENT = False` | the `+7` assumption, keeping roster levels, houses, shrines and tool tiers. The targeted revert if the `−0.52% / −1.26%` adverse slice turns out to be the wrong call — and the one rung that makes the totals rise *further*, so reach for it only on evidence, never to make a number look better. |
| 3 | `ROSTER_USE_TOOLS = False` | the manual checkbox, keeping roster levels and houses. |
| 4 | `ROSTER_USE_HOUSES = False` / `ROSTER_USE_LEVELS = False` | either half of the "free" improvement. |
| 5 | `ROSTER_USE_SHRINES = False` | the guild-wide shrine constant **and** `simulate_race`'s once-per-race hoist — bit-for-bit, pinned by `test_shrines_off_is_bit_identical_to_the_hoisted_path`. Note this rung gives up the largest favourable term after levels. |
| 6 | `ROSTER_ADMITS_NEW_MEMBERS = False` | "reported, not seated": LI returns to 101 members, the five lose their seats, the sign-up WARNING returns, and LI stops being cap-constrained. Independent of rungs 2–5 — it is a *membership* revert, not a rate one — so it can be pulled alone. |
| 7 | `RISK_SIGMA_SYSTEMATIC = 0.0131` | the pre-recalibration risk discount. The old value and its derivation stay in the comment for exactly this. |

**The operational rollback needs no code at all.** If the Apps Script deployment is removed,
the tab renamed, or its header shifted, Risk 2's degradation path drops the build back to the
manual tab automatically, with a warning and an on-page banner. That is the rollback that
matters at 03:00 UTC when the daily cron runs.

**Git rollback**, if a phase must go entirely:

```bash
git log --oneline $(cat /tmp/R0-baseline-sha)..HEAD    # one commit per phase
git revert <phase-sha>                                  # phases are independent
# or, wholesale:
git checkout $(cat /tmp/R0-baseline-sha) -- src/ tests/
uv run python -m pytest tests/ -v
uv run --no-dev python -m src.build && diff -r _site /tmp/R0-site
```

**Verification after any rollback:** `pytest tests/ -v` green, and a full build `diff -r`
against the R0 snapshot for rung 1.

---

## 11. Open questions and deliberately deferred work

### 11.1 Two shrine questions CLOSED, one opened
**Closed.** Per-member shrines are *in* this change (§5.4), and the open question at
`config.py:1136-1141` — shrine level vs separately-bought buff level — is **answered**: the
shrine level is the guild's cap, the buff level is the member's purchase, and it is the
purchase that reaches the rate (§2.2). R7.1 deletes the comment.

**Opened.** The roster gives each member's *current* purchased level, not their rate of
buying. `probe_shrine_adoption` (§5.5) says what unbought headroom is worth today; it cannot
say how fast the guild will actually close it, which is what `probe_shrine_upgrade`'s
`points_gained_at_full_adoption` would need to convert into an honest payback period. Two
consecutive roster captures would give an adoption *rate* and make that possible.
`capturedAt` and `revision` are already per member, so the data to do it will accumulate on
its own from the first build onward — this needs patience, not work.

### 11.2 The `stableGear` block — the highest-value follow-up, and out of scope
The upstream module can be made to export `gear_{pouch,trinket,neck,ring,earrings,back,feet}`
+ their `…Enh` (14 columns). Those slots are **most of what `RISK_SIGMA_SYSTEMATIC` still
prices after R6** — `gear_speed`, `gear_efficiency` and `gear_gathering` in `calibrate.DEFAULT`
are exactly "the sheet has no column for the neck, ring or earring slots". Observing them
would let the largest surviving term be measured rather than assumed.
It needs a `mode:"replace"` write to the upstream module's settings, which is not something
this repo can or should do. **Named here so it is a decision someone takes, not a thing
nobody remembers.**

### 11.3 Top / Bot stay manual — permanently
Body and legs are deliberately excluded upstream as rotating combat slots. No plan should
expect them.

### 11.4 `characterId` as the join key
The roster's own stable key survives renames; the manual tab has no id column, so name is the
only bridge available today. One column on the officers' tab would retire the
case-insensitive join, the ambiguity rule, and the `yiyaa`/`yiyya` problem in §5.6. Cheap for
them, impossible for us. **Worth asking.**

### 11.5 Ground truth — the only measurement that proves "correction", not "differently wrong"
R5's reconciliation proves the implementation matches an independent measurement of the
*same inputs*. It does **not** prove the model now matches the game — and with the net moving
**up** by 3–6%, that gap is the plan's largest residual risk rather than a footnote. The
`currentTrialsData` capture described in `research/trial-messages.md` (used the same way for
partial credit in the prior plan's §2.7) carries the guild's actual award. The pre-change
model was pessimistic on levels and shrines and optimistic on tools; the post-change model
should sit measurably closer to the observed award, and **in which direction it was wrong
before is itself checkable** against the last few weeks' recorded awards.
**Resolution:** one capture after the next trial, and a comparison against both the R0 and
the R5 manifests. Until then R5's claim is "the correction was implemented correctly", which
is a weaker and honestly-stated thing — and the reason the provenance strip (R4) ships before
the flip rather than after.

### 11.6 `TOOL_ENHANCE_WHEN_UNKNOWN` — 0, against an observed mode of 5
Provisional (§5.3). **Trigger:** if named-tool-with-blank-enhancement exceeds 5% of matched
member-skills on either guild, resolve before R5's flip. The count is printed every build so
the trigger cannot be missed.

### 11.7 Roster-only members — CLOSED, and reversed
`ROSTER_ADMITS_NEW_MEMBERS = True` since R2 (§5.6, revised): the rename hazard that carried
the original `False` was checked against the live tab and is false, and both guilds turn out
to seat every member they have, so the five are the only spare capacity in existence. The
size of the effect is still worth reading off the R5 tier table, but it no longer decides
anything.

### 11.8 Members, not the cap, are the binding constraint — until admission, on LI
The prior plan's §3.7 asked whether `TRIAL_PARTY_CAP` is real and what its value is, calling
it "a magic number". The R0 manifest answers a question nobody thought to ask beside it, and
the answer redirects §3.7: **neither guild is currently cap-constrained.** SC seats
28 + 24 + 28 + 27 = 107 — its entire roster — against 4 × 28 = 112 available seats; LI seats
25 + 24 + 26 + 26 = 101, its entire roster, against 104. Both have run out of *people*. Every
published party size is therefore set by headcount, not by the cap and not by the
1%-per-member penalty, which means the cap has not in fact bound anything over the period
these plans have spent arguing about it.

Admission changes that, on one guild, immediately: LI goes to **106 members in 104 seats** and
becomes cap-constrained, while SC (107 in 112) does not. From R5 onward the two guilds sit in
**different regimes**, and LI is where the value of the cap starts to matter for the first
time. Recorded here rather than acted on — this plan does not touch `TRIAL_PARTY_CAPS`, and
should not — but the next person to open §3.7 should know the question has just gone live for
exactly one guild, and which one.

A corollary that is easy to get backwards: recruiting is currently worth more than raising the
cap on both guilds, and after R5 that reverses on LI.

### 11.9 The mirror-image member, and the one column that would retire both cases
LI's manual tab holds one member (`OTZ`) the roster has never seen — the exact inverse of the
five roster-only names. The merge keeps them, because the manual tab is evidence too and its
silence about somebody is no more probative than the roster's. Both cases are symptoms of one
missing thing: **there is no shared key.** `characterId` on the manual tab (§11.4) would
retire the roster-only case, the manual-only case, the case-insensitive join and the
ambiguity rule, in a single column.

### 11.10 Tool loot and XP stats
`TOOL_STATS` deliberately drops `<skill>RareFind` and `<skill>Experience`. They are real and
they are worth money; they do not change how fast work gets done, and this model is a rate
model. Same rule as Rarity, Spirit and Scholar in `guild_shrine_bonuses`. Recorded so that
their absence reads as a decision rather than an omission.

---

## 12. Success criteria

The change is complete when:

- ✅ `ROSTER_SOURCE_ENABLED = False` reproduces the R0 build **byte-for-byte** (`diff -r`), and
  the golden test pins the same property offline.
- ✅ Every one of the ~90 pre-existing tests passes **unmodified**.
- ✅ The join reports 107/107 on SC and 100/101 on LI, with the unmatched remainder named in
  the build log — and LI's five roster-only members are SEATED (§5.6, revised), reported as
  previously dropped, and absent from `index.html`'s register.
- ✅ A gear-hiding member demonstrably gets roster levels and houses and a manual tool — the
  per-field property, held by a test rather than by inspection.
- ✅ Tool columns are read by name, and a shuffled tool block parses identically.
- ✅ A renamed roster column fails loudly and *degrades* rather than stopping the deploy.
- ✅ `tool_bonus` reproduces all four shipped constants exactly at `+7`.
- ✅ Every R5 slice lands within `±0.1pp` of its band (§2.3): levels `+2.41 / +6.57`,
  houses `+0.03 / −0.16`, shrines `+1.33 / +0.89`, tools `−0.52 / −1.26`, combined
  `+3.30 / +6.00` — with slice 4 **negative** and the interaction residual under 0.1pp.
- ✅ Shrines are per-member, Rarity/Spirit/Scholar still contribute exactly 0.0, and
  `ROSTER_USE_SHRINES = False` is bit-identical to today's hoisted path.
- ✅ `MemberBonuses.speed` / `.efficiency` still report only what the member owns; the shrine
  terms are still applied at the point of use in `_prepare_member`, in the original order.
- ✅ `probe_shrine_upgrade` reports an immediate gain of exactly zero, and
  `probe_shrine_adoption` publishes the unbought headroom the guild can close for free.
- ✅ The answered shrine question is **deleted** from `config.py:1136-1141`, not left
  standing.
- ✅ `RISK_SIGMA_SYSTEMATIC`'s new value is traceable to a published ablation row, and the
  R5 and R6 deltas are reported separately.
- ✅ The totals **rose** by the predicted amount, tier changes are gains rather than losses,
  and any tier *lost* is explained rather than absorbed.
- ✅ Both pages state, for every member, which of the three sources their numbers came from,
  and how old the capture is; and the `Assumptions & caveats` block no longer claims anything
  the roster has made false.
- ✅ **LI's member count rises 101 → 106**, and the build log's
  `WARNING (li): 5 sign-up name(s) match NO member … IronPugs, U3, auuughhh, yiyaa, yiyya`
  **disappears**. SC's count stays 107 and SC's run 5 is byte-identical to its run 4.
- ✅ `yiyaa` and `yiyya` are both seated, as two members with two `characterId`s.
- ✅ Admitted members carry `top is False` / `bot is False`, are counted as such in
  provenance, and the `index.html` (101) vs `trials.html` (106) discrepancy is captioned
  rather than left to look like a bug.
- ✅ LI's manual-only member (`OTZ`) survives the merge.
- ✅ The build's per-unit timings are unchanged outside noise.
- ✅ `research/roster-as-primary-source.md` carries the before/after tables, the four slices,
  run 5's composition table, the ablation, and §11's open questions — including the finding
  that neither guild was cap-constrained before this change and that LI becomes so after it.

---

## 13. References

- **ResearchPack:** `.claude/plans/roster-as-primary-source-researchpack.md`
- **Prior plan (register and rigour bar):**
  `.claude/plans/guild-trials-2026-08-patch-implementation-plan.md`
- **Seams:** `src/trials.py:203` `_resolve_level_and_checks`, `:294` `guild_shrine_level`,
  `:298` `guild_shrine_bonuses`, `:386` `member_bonuses`, `:574` `_prepare_member` (and its
  bit-exactness docstring), `:618-619` where the shrine tuple is applied, `:771`/`:855`/`:1198`
  the three hoist sites, `:1612` `ShrineUpgrade`, `:1653` `probe_shrine_upgrade`; `src/reader.py:26-44`;
  `src/scraper.py:68-91` `fetch_tab_csv`, `:94-119` the guard precedent;
  `src/build.py:103` `member_tab`, `:3452` `_GuildInputs`, `:3480` `_fetch_guild`,
  `:3784-3801` the unmatched-name reporting precedent, `:2115` the caveats block;
  `src/calibrate.py:102-123` the multiplier loader, `:130-139` the `(base, per)` pairs,
  `:190-290` `Sources`, `:369` the 5-tuple unpack that pins `_resolve_level_and_checks`;
  `src/config.py:103-107` `GVIZ_URL`, `:108-128` the `&headers=0` account,
  `:692-699` the tool constants, `:979` `DEFAULT_HOUSE_LEVEL`, `:1120-1148` the shrine buff
  table, levels and the open question this change answers, `:583` `RISK_SIGMA_SYSTEMATIC`.
- **Game data:** `research/item-stats.json` — the full tool catalogue (§2.1) and the 21-entry
  `enhancementLevelTotalBonusMultiplierTable`.
- **Doctrine this plan follows:** `src/draw.py`'s docstring on loud failure over quiet
  fallback; `README.md` on the one-directional credential-free pipeline; the
  one-line-rollback convention (`TRIAL_PARTIAL_CREDIT_RATE`, `OPT_OBJECTIVE`,
  `BUILD_PARALLEL`, `SHRINE_BUFFS_APPLY_IN_TRIALS`).

---

## 14. Plan metadata

- **Created:** 2026-08-31
- **Based on:** the live-verified ResearchPack of the same date, plus a read of the live
  source tree at `afe14c5`
- **Phases:** 9 (R0 baseline … R8 documentation), one commit each. The shrine *rate* fix
  sits in R3/R5 rather than late, because it is a correctness fix affecting 88–95% of
  members; only the shrine *probes* remain in R7.
- **Files:** 2 new modules/tests + 1 research note, 7 modified
- **New tests:** ~48 named cases, including one golden byte-for-byte rollback test and three
  bit-exactness tests guarding the shrine change
- **Estimated complexity:** medium-high — the code is small and surgical; the *measurement*
  discipline is the bulk of the work, and deliberately so
- **Risk level:** medium, concentrated in R5/R6 where the published numbers move — and note
  they now move **upward**, which is the direction that attracts less scrutiny and therefore
  needs more of it
