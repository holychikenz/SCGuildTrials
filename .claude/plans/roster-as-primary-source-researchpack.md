# ResearchPack — "SC/LI Roster" as the primary member-data source

Gathered 2026-08-31 against the LIVE sheet and the live source tree. Every figure
below is measured, not assumed.

> **CORRECTED 2026-08-31, after the first draft.** Two things in the original were wrong and
> both change the headline. (a) Guild shrines are **not** a guild-wide buff that the roster
> merely reports more freshly — the guild level is a **cap** and the member's own purchased
> level is what enters the rate (**§2.1**). (b) The original "size of the prize" priced only
> the tool slice and concluded that parties get **slower**. Measured across all four slices
> through the repo's own rate path, they get **faster** — SC +3.30%, LI +6.00% (**§5.0**).
> The tool pessimism is real but it is the smallest of the terms that matter.
> (c) The five roster-only LI members are **real, distinct members who all signed up**, and
> the `yiyaa`/`yiyya` "rename" reading offered in the first draft is falsified both by
> measurement and by the upsert-on-`characterId` writer (**§3.1**). They are admitted.

## 1. What exists now, on the sheet

Two new tabs, written by the `profiles-endpoint` branch's Apps Script
(`apps-script/profiles/Code.gs`) from the Tampermonkey `guild-profile-{store,sheet}`
modules:

| tab | gid | rows | cols |
|---|---|---|---|
| `SC Roster` | 1027847767 | 107 members | 78 |
| `LI Roster` | 618580845  | 105 members | 78 |

**Addressable by name through the existing credential-free path.** Plain
`config.GVIZ_URL.format(sheet="SC Roster")` returns a clean, unmangled header row
(verified). Do NOT pass `&headers=0` — that makes gviz blank the label of every
numeric column. No gid, no API key, no change to the pipeline's one-directional
"public CSV only" property.

### The 78 columns (verified live, in order)

```
0  name              1  characterId       2  guildId        3  guildName
4  guildRole         5  capturedAt        6  revision       7  setsComplete
8-13   set_beginner set_novice set_adept set_veteran set_elite set_champion
14-23  milking foraging woodcutting cheesesmithing crafting tailoring
       cooking brewing alchemy enhancing                (skill LEVELS)
24-30  stamina intelligence attack defense melee ranged magic
31-47  house_dairy_barn garden log_shed forge workshop sewing_parlor kitchen
       brewery laboratory observatory dining_room library dojo armory gym
       archery_range mystical_study                     (levels 0-8)
48-57  shrine_{force,tempo,spirit,rarity,scholar}_{combat,skilling}
58-77  tool_<skill> / tool_<skill>Enh  ×10, alphabetical by skill:
       alchemy brewing cheesesmithing cooking crafting enhancing
       foraging milking tailoring woodcutting
```

Blank vs zero is meaningful and the endpoint preserves it: `0` = catalogue item the
member never acquired; **empty** = withheld (`hideWearableItems`) or unknown.

### Column order caveat (upstream, worth knowing)

`itemLocationDetailMap` has no `sortIndex`, so the tool block's order comes out
alphabetical when client data was captured but in skill order from the module's
`FALLBACK`. **Read tool columns by header name, never by position.**

## 2. Mapping roster → the existing model

| model input | manual sheet today | roster column | verdict |
|---|---|---|---|
| skill level | block col +0 | `milking`…`enhancing` (Alchemy = the "Bell Farming" column) | roster wins |
| house level | block col +1 ("H") | `house_dairy_barn`…`house_observatory` | roster wins |
| tool tier | "Tool" checkbox = **Celestial** | `tool_<skill>` name | roster wins |
| **tool enhancement** | *not expressible* — assumed **+7** | `tool_<skill>Enh` | **new knowledge** |
| shrine levels | `config.GUILD_SHRINE_LEVELS`, one global map for both guilds, from a 2026-07-22 capture | `shrine_force_skilling`, `shrine_tempo_skilling`, **per member** | **new knowledge, and the global map is the WRONG SHAPE, not merely stale** — see §2.1 |
| skilling top / bottom | "Top"/"Bot" checkboxes | **absent** — body/legs are excluded upstream as rotating combat slots | **manual only** |
| main class / flex | cols 1-2 | absent | manual only (unused by the model) |
| cape, family piece, neck, ring, earrings, pouch | none — assumed | absent **unless the module's `stableGear` toggle is switched on** (adds `gear_{pouch,trinket,neck,ring,earrings,back,feet}` + `…Enh`, 14 cols) | future lever, needs a `mode:"replace"` write |

House-room ↔ skill map (confirmed against the game catalogue):
milking→dairy_barn, foraging→garden, woodcutting→log_shed, C.Smithing→forge,
crafting→workshop, tailoring→sewing_parlor, cooking→kitchen, brewing→brewery,
Bell Farming/Alchemy→laboratory, enhancing→observatory.

### 2.1 Shrines: the guild level is a CAP, the member's level is the PURCHASE

Corrected 2026-08-31 from the guild's own account of the mechanic:

> "The guild purchases the ability to upgrade shrines, then the user has to spend resources
> in order to actually obtain the upgrade. The guild may unlock level 5, but a user may only
> be able to afford up to level 3. It's that level 3 that we track in that column and that
> improves their stats."

So the two things are in **series**, not in competition: the guild's shrine level (bought
with guild points) is a **ceiling**, and the member's buff level (bought with their own
resources) is what actually multiplies their stats. `shrine_<name>_skilling` on the roster is
the member's purchase.

The live data corroborates it exactly — every member sits at or below a per-guild ceiling,
and the ceiling differs between guilds:

| | `force_skilling` | `tempo_skilling` | spirit | scholar | rarity |
|---|---|---|---|---|---|
| **SC** (n=107) | `{0:5, 1:13, 2:13, 3:23, 4:53}` mean 2.99, **max 4** | `{0:7, 1:6, 2:12, 3:23, 4:59}` mean 3.13, **max 4** | max 2 | max 2 | all 0 |
| **LI** (n=105) | `{0:10, 1:5, 2:34, 3:56}` mean 2.30, **max 3** | `{0:10, 1:7, 2:28, 3:60}` mean 2.31, **max 3** | max 1 | max 1 | all 0 |

The per-guild **maximum is the unlocked cap** (SC 4, LI 3). Nobody exceeds it; many sit below
it, and that gap is spendable by the member at **no guild cost**.

Three consequences:

1. `config.GUILD_SHRINE_LEVELS = {"force": 1, "tempo": 1}` is stale, per-guild-wrong, and —
   more fundamentally — **models as one guild-wide constant a quantity that is a per-member
   purchasing decision**. Members whose level is something other than the modelled 1:
   SC force 94/107 (88%), SC tempo 101/107 (94%), LI force 100/105 (95%), LI tempo 98/105
   (93%). Mostly understating (SC mean force 2.99 vs 1.0), but not uniformly: 5 SC and 10 LI
   members hold level 0, where the model currently *overstates*.
2. **This answers the open question at `config.py:1136-1141`** — which of the two ladders
   drives the multiplier. Both do, in series: guild level = cap, buff level = purchase, and
   it is the purchase that reaches the rate. The question can be retired.
3. `trials.probe_shrine_upgrade` prices a guild cap raise as though every member instantly
   gained the level. Under the corrected mechanic a cap raise changes **no member's stats on
   the day it completes**, so that probe's figure is a distant ceiling rather than the lower
   bound its docstring claims.

## 3. The join — measured

Joining on the raw name string **silently loses members**:

| | manual | roster | exact-match | case-insensitive |
|---|---|---|---|---|
| SC | 107 | 107 | 101 (6 lost) | **107 (all)** |
| LI | 101 | 105 | 95 (6 lost) | **100 of 101** |

Casing drifts on both sides (`dome`/`Dome`, `VIadd`/`Viadd`, `FeaI`/`Feai`).
**The join must be case-insensitive**, and the unmatched remainder must be reported
loudly, not swallowed — the same discipline `build.py:3790-3797` already applies to
sign-up names that match no member.

### 3.1 The five roster-only members are real — CORRECTED 2026-08-31

LI's roster carries 5 members the manual tab has never heard of: `IronPugs` (id 280884),
`U3` (281111), `auuughhh` (117231), `yiyaa` (287196), `yiyya` (287200).

**An earlier reading of this paragraph offered "the last pair looks like a rename" as
plausible. It is not, and the correction matters because that reading was load-bearing for a
decision to exclude all five.** Two grounds, the second decisive:

- **Measured.** `yiyaa` and `yiyya` hold two distinct `characterId`s and their stats differ —
  shrines force/tempo 2/3 against 2/2, Holy Enhancer **+5** against **+6**, C.Smithing 105
  against 107 (Milking 109 for both).
- **Structural.** `apps-script/profiles/Code.gs` sets `KEY_COLUMN = 'characterId'` and
  **upserts** on it, so a rename updates its row *in place* and cannot produce a second one.
  **Two rows can only ever mean two characters.** A rename is invisible to the roster's row
  count by construction.

The general property is worth stating once, because it decides where a guard belongs: the
roster is keyed on an identifier that renames preserve, so the name-collision and ambiguity
guards belong on the **manual** side of the join — where names are the only key — and nowhere
on the roster side.

**Three independent pieces of evidence say the five are guild members:** they are on the
roster with complete records (levels, houses, shrines, tools), captured 2026-08-28 like
everyone else; the game itself lists them in the guild (`guildRole = member`, `guildId` 240);
and **all five signed up for this week's trials** — the R0 build log records
`WARNING (li): 5 sign-up name(s) match NO member on the 'LI Member Data' tab and were
IGNORED: IronPugs, U3, auuughhh, yiyaa, yiyya`. Against that, the only evidence for exclusion
is silence from a hand-maintained tab which the same log shows to be six names behind on
casing alone.

**The stake is larger than five names.** The R0 manifest shows both guilds already seating
every member they possess — SC 28+24+28+27 = 107 of 107, LI 25+24+26+26 = 101 of 101 —
against 112 and 104 available seats. Neither guild is cap-constrained; both have run out of
*people*, so these five are the only additional capacity in existence. Four sit at or near the
LI median in the drawn skills (`auuughhh`: Milking 113 vs a median of 112, Tailoring 113 vs
108); `IronPugs` sits well below it and may not pay for its seat — which is the optimizer's
decision to make, and it can now make it. Note that admitting them takes LI to 106 members in
104 seats, i.e. **cap-constrained for the first time**.

The mirror-image case exists too and must not be lost in the same breath: LI's manual tab
holds one member (`OTZ`) the roster has never seen.

`characterId` is the roster's own stable key and survives renames; the manual tab has
no id column, so name is the only bridge available today. One id column on the manual tab
would retire the roster-only case, the manual-only case, the case-insensitive join and the
ambiguity rule together.

## 4. Coverage and staleness — measured

- Every roster row was captured on **2026-08-28** (one harvest sweep). `capturedAt`
  and `revision` are per member, so a staleness rule is possible and cheap.
- **9 of 107 SC** and **7 of 105 LI** members hide their gear: all 20 tool columns
  blank. Skills, houses and shrines still populate for them.
- Manual-tab levels are stale, badly on LI: roster − manual level delta
  SC `{-1:15, 0:741, +1:294, +2:17, +3:3}`;
  LI `{-1:7, 0:459, +1:327, +2:142, +3:44, +4:10, … +17:1}`.
  Seven LI members are 5-17 levels above what the model believes.
- Manual house cells are near-right but drift (`+1` on 33 SC / 57 LI cells), and LI
  leaves 59 of 88 blank — those currently fall back to `DEFAULT_HOUSE_LEVEL = 4`,
  a fallback `calibrate.py:392` already knows is biased high (LI's filled cells
  average ~3.1). The roster removes the guess entirely.

### The "Tool" checkbox means Celestial — confirmed

Cross-tabulated over every matched member × skill:

| | roster Celestial | roster Holy | blank |
|---|---|---|---|
| SC tick=TRUE | **127** | 3 | 10 |
| SC tick=FALSE | 1 | **846** | 80 |
| LI tick=TRUE | **58** | 4 | 12 |
| LI tick=FALSE | 4 | **860** | 58 |

So the manual checkbox is faithful, and the roster agrees with it — but the roster
additionally sees the tiers the checkbox cannot express (`Rainbow Enhancer`,
`Azure Spatula`, `Burble Pot`, `Cheese Alembic`, `Rainbow Alembic`).

## 5. The size of the prize — measured

**Read §5.0 first: the tool slice below is one of four terms, and the smallest of the three
that matter. The net across all four is FAVOURABLE.**

### 5.0 All four slices, through this repo's own rate path

Measured through `trials._prepare_member` / `trials.success` at tier 11 over every matched
member × skill — not re-derived:

| slice | SC mean | SC median | SC p05 / p95 | LI mean | LI median | LI p05 / p95 |
|---|---|---|---|---|---|---|
| 1 — levels (roster vs manual) | **+2.41%** | +0.00% | +0.00 / +13.19 | **+6.57%** | +0.81% | +0.00 / +27.64 |
| 2 — houses | +0.03% | +0.00% | +0.00 / +0.00 | −0.16% | +0.00% | −2.14 / +1.41 |
| 3 — shrines (per-member vs global L1) | **+1.33%** | +1.40% | −0.23 / +2.30 | **+0.89%** | +1.13% | −0.23 / +1.70 |
| 4 — tools (real tier + enh vs assumed +7) | **−0.52%** | +0.00% | −3.79 / +4.55 | **−1.26%** | −1.35% | −4.89 / +4.55 |
| **all four combined** | **+3.30%** | +1.75% | −2.85 / +14.29 | **+6.00%** | +2.05% | −3.69 / +26.81 |

**70% of SC slot-observations and 63% of LI's get faster.** The tool-augment pessimism is
real and it is the only adverse term; it is outweighed roughly four-to-one by stale levels
and understated shrines. Parties get **faster**, not slower — which is the direction that
attracts less scrutiny and therefore needs more of it.

The combined figure is not the sum of the parts (SC 3.30 vs 3.25; LI 6.00 vs 6.04); that
residual is the interaction term and it is a useful check on any implementation.

**Which tool figure is authoritative.** §5.1 below gives `−0.66% / −1.50%` for the tool
slice; the table above gives `−0.52% / −1.26%`. **The table above is authoritative**, because
it goes through the repo's own rate path and therefore includes the Enhancing **success**
channel (where a tool feeds `success_bonus`, not speed) and the `math.floor(work_power(...))`
step in `_prepare_member`. §5.1 is a speed-channel-only calculation and remains a useful
independent cross-check on that channel alone; the ~0.15pp gap between the two is expected
and explained.

### 5.1 The tool slice alone (speed channel only)

Tool enhancement is **not** +7. Observed distribution (SC): `{0:6, 3:16, 4:38,
5:298, 6:139, 7:254, 8:92, 9:29, 10:91, 11:12, 12:3, 13:1, 14:1}`; LI is lower still
(modal +5). Repricing each observed tool through
`item-stats.json.enhancement.enhancementLevelTotalBonusMultiplierTable` and holding
everything else fixed, the change in that member's action rate versus the model's
assumed +7:

| | mean | median | p05 | p95 | min | max | slower than modelled |
|---|---|---|---|---|---|---|---|
| SC | **−0.66%** | −1.35% | −3.80% | +4.56% | −11.19% | +13.52% | 53% of slots |
| LI | **−1.50%** | −2.62% | −4.90% | +3.19% | −11.19% | +8.32% | 66% of slots |

Two consequences, and the second is the important one:

1. **A systematic optimism** of ~0.7% (SC) / ~1.5% (LI) in every party's rate on the speed
   channel — comparable in size to the whole calibrated `RISK_SIGMA_SYSTEMATIC = 0.0131`,
   and pointed the wrong way for a model whose job is to say whether a tier holds. NB: this
   term is real but it is **outweighed** by the level and shrine corrections (§5.0), so the
   *net* effect of the whole change is favourable.
2. **A ±10% spread between members that the model currently cannot see.** Since the
   optimizer's entire job is ranking members into seats, an unmodelled 24-point
   spread in per-member rate is a ranking error, not merely a scaling error.

## 6. The seam — where richer data must enter

- **Parse.** `src/reader.py:26-34` (`SkillEntry`) / `src/reader.py:37-44` (`MemberRow`);
  populated by `src/scraper.py:122-166` (`parse_gviz`) and `src/reader.py:160-166`.
  `SkillEntry` is the natural carrier for per-skill roster facts.
- **Rate.** `src/trials.py:386` `member_bonuses(...)` is the *only* place per-member
  data becomes a bonus; `src/trials.py:203` `_resolve_level_and_checks` is the only
  read of the sheet. `src/trials.py:574` `_prepare_member` carries it into the hot
  loop; `simulate_race` (`trials.py:1160`) never sees a `MemberRow`.
- **Constants that must become functions of an enhancement level:**
  `TOOL_SPEED_{HOLY,CELESTIAL}_PLUS7` (`config.py:692-693`),
  `TOOL_SUCCESS_{HOLY,CELESTIAL}_PLUS7` (`config.py:698-699`). Their `(base, per)`
  pairs already exist in `calibrate.py:130-139`; the multiplier table is loaded at
  `calibrate.py:102-123`.
- **Shrines.** `trials.py:294` reads `config.GUILD_SHRINE_LEVELS` once per race
  (`trials.py:1198`, also `:771`, `:855`) and adds the tuple at `trials.py:618-619`.
  Per-member shrine levels break that "resolve once per race" hoist — but **not
  expensively, and the first reading of this bullet overstated it**: `member_bonuses`
  already runs once per member per race (`_prepare_member` calls it, once per member, not
  once per tier), so the added work is a dict read and two multiplications per member per
  race against a `success()` call that already runs ~13 times per member per race. The real
  constraint here is **bit-exactness, not speed**: `MemberBonuses.shrine_speed` /
  `.shrine_efficiency` are deliberately separate fields applied *at the point of use*
  (`work_power(level, eff + shrine_eff)`, `action_seconds(skill, speed + shrine_speed)`), and
  `_prepare_member`'s docstring records a live incident where re-associating that arithmetic
  moved a party rate by one ULP and reshuffled every SC party. Change how the fields are
  POPULATED; do not change where they are APPLIED.
- **Plumbing.** `src/build.py:3480` `_fetch_guild` is where a second fetch belongs;
  `_GuildInputs` (`build.py:3452`) is the carrier; `GuildSite.member_tab`
  (`build.py:103`) is the per-guild tab name, so a `roster_tab` sits beside it.

## 7. Downstream consequences a plan must address

1. **Calibration is re-priced, not merely improved.** `calibrate.py` prices
   `augment=±3 per slot` (`:272`), `tool_flip=0.03` (`:273`) and `house_blank`
   (`:264`) as *uncertainty*. Observing all three should shrink
   `RISK_SIGMA_SYSTEMATIC`, which feeds `expected_credit_points` — the shipped
   objective. Leaving sigma untouched keeps a now-false pessimism; changing it
   without re-running the calibration substitutes a guess for a measurement.
2. **The mean moves in our FAVOUR — which is the more dangerous direction.** Corrected
   2026-08-31: across all four slices SC gains **+3.30%** and LI **+6.00%** of mean
   per-member rate (§5.0). Only the tool slice is adverse. A number that falls invites
   scrutiny; a number that jumps 6% in the guild's favour gets accepted, and a bug that
   inflates rates is then indistinguishable from the correction it hides inside. Any plan
   must therefore verify **each slice separately against its own band**, including — and
   especially — the three favourable ones, and must require the tool slice to come out
   negative as the evidence that this is a correction and not a uniform coat of optimism.
3. **Provenance must be visible.** The site's own discipline is that a stale or
   guessed input is captioned (the "MAY BE STALE" banner, the buff-ladder outline).
   A member whose numbers come from the roster, from the manual tab, or from a
   constant is three different epistemic states and the page should say which.
4. **Fallback must be per-field, not per-member.** A gear-hiding member has real
   levels, real houses, real shrines and no tools; the right behaviour is roster for
   what it knows and manual for the rest, field by field.
5. **A structure guard is mandatory.** `SC Roster` is written by a separate
   deployment that can change its header when a module toggle moves. The pipeline's
   standing rule (`README.md`, `config.py:1-7`) is that a layout change fails loudly.
6. **Top/Bot stay manual, and always will** unless the upstream module starts
   exporting body/legs — which it deliberately does not. NB the consequence for §3.1's
   admitted members: they have no manual row, so their `top`/`bot` are necessarily `False`
   and their efficiency is understated by up to two `ARMOUR_EFFICIENCY_PLUS7` terms
   (`0.2364`). Admit on the evidence held, not the evidence wished for — but say so on the
   page, and note that any tier gain they produce is therefore a floor.
7. **Admission is not a rate change and must not be measured as one.** The four slices in
   §5.0 are mean Δrate over *matched* members; the five admitted members are by construction
   outside that population. Measuring them inside it would change the denominator mid-table
   and manufacture a spurious interaction residual — discrediting the very check §5.0's
   residual exists to provide. Measure admission separately, as a composition change.
