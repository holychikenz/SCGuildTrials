# Guild shrines: which two buffs enter the tier race, and why buying them is a mistake

**Status**: the buff magnitudes, the shrine→buff mapping and the guild-point cost
ladder are **CONFIRMED game data**, read directly from the client dump and
re-verified on 2026-08-11. **The dump is PRE-patch** — see below — but the patch
notes themselves supply the cross-check that says the two buffs this model cares
about were *not* re-tuned (§3). What is **NOT** confirmed is the guild's live
**buff** level, because a shrine level and a buff level are two different ladders
and only the first is in any capture we hold (§4, §6).

**Source**: `/Users/morgan/pie/cowstuff/milkyway_client_info.json`,
`gameVersion v1.20260715.0`, `versionTimestamp 2026-07-16T03:24:51Z`. Keys read:
`guildBuffDetailMap` (10 entries) and `guildShrineDetailMap` (5 entries).
**This dump predates the 2026-08-11 patch**; refreshing it is Phase 0 step 1 of
the implementation plan and the cheapest route to resolving §6.

**Why this note exists**: the patch made the shrines' *skilling* buffs apply
**inside Trials**, so two of them now enter this repo's rate model for the first
time. Survey Corps holds both at level 1, which means the shipped model is
currently wrong by a measured **+0.61 points per trial** (§5). The companion note
`research/partial-tier-credit.md` carries the patch notes verbatim and the rest of
the patch.

---

## 1. The ten buffs, and the only two that matter here

Each `guildBuffDetailMap` entry is keyed to a shrine (`shrineHrid`) and flagged
`isCombat`. Ten entries: five shrines × {skilling, combat}.

| buff hrid | shrine | `isCombat` | `typeHrid` | value | enters the race? |
|---|---|---|---|---|---|
| `force_skilling` | `/guild_shrines/force` | false | `/buff_types/efficiency` | **flat 0.005 + 0.005/level** | **YES** → `work_power` |
| `tempo_skilling` | `/guild_shrines/tempo` | false | `/buff_types/action_speed` | **flat 0.005 + 0.005/level** | **YES** → `action_seconds` |
| `rarity_skilling` | `/guild_shrines/rarity` | false | `/buff_types/rare_find` | flat 0.01 + 0.01/level | no — **loot** |
| `spirit_skilling` | `/guild_shrines/spirit` | false | `/buff_types/essence_find` | flat 0.02 + 0.02/level | no — **loot** |
| `scholar_skilling` | `/guild_shrines/scholar` | false | `/buff_types/wisdom` | flat 0.005 + 0.005/level | no — **XP** |
| `force_combat` | force | true | `damage` | ratio 0.003/lvl | no |
| `tempo_combat` | tempo | true | `attack_speed`, `cast_speed` | 0.004/lvl each | no |
| `spirit_combat` | spirit | true | `max_hitpoints`, `max_manapoints` | ratio 0.01/lvl each | no |
| `rarity_combat` | rarity | true | `rare_find` | 0.01/lvl | no |
| `scholar_combat` | scholar | true | `wisdom` | 0.005/lvl | no |

A verbatim entry, so the shape is auditable:

```jsonc
{
  "hrid": "/guild_buffs/force_skilling",
  "shrineHrid": "/guild_shrines/force",
  "isCombat": false,
  "buffs": [{
    "uniqueHrid": "/buff_uniques/efficiency_guild_buff",
    "typeHrid": "/buff_types/efficiency",
    "ratioBoost": 0, "ratioBoostLevelBonus": 0,
    "flatBoost": 0.005, "flatBoostLevelBonus": 0.005,
    "startTime": "0001-01-01T00:00:00Z", "duration": 0
  }],
  "levelCosts": { "1": { ... }, ... "20": { ... } },   // see §4 — NOT guild points
  "sortIndex": 2
}
```

`flatBoost == flatBoostLevelBonus`, so by the in-game rule
`flatBoost + (level−1)·flatBoostLevelBonus` the grant is exactly
**`per_level × level`** — the identical pattern the guild *buildings* follow
(`research/trial-messages.md:127-130`), and the one `config.py` already relies on
for them.

---

## 2. The hard rule: only Force and Tempo may touch the rate model

**Force (efficiency) and Tempo (action speed) are the only two shrines that enter
the tier race.** They map onto terms the race already has:

* **Force → `/buff_types/efficiency`** → composed into `work_power(level,
  efficiency + shrine_efficiency)`; efficiency is folded deterministically into
  the per-action payload, exactly as the captures show the engine doing
  (`progressPerAction: 133` alongside `efficiency: 0.317`,
  `research/trial-messages.md:186-207`).
* **Tempo → `/buff_types/action_speed`** → composed into `action_seconds(skill,
  speed + shrine_speed)`.

**Rarity, Spirit and Scholar must never touch the rate model, at any level.**
This is not a modelling preference, it is what the buff types mean:

* `rare_find` and `essence_find` change **what drops**, not how fast work
  accumulates. The trial race is a pure `targetWorkValue` grind
  (`research/trial-messages.md:262-264`); loot is not in the loop.
* `wisdom` changes **XP gained**, which the race does not read at all.

Writing them into `speed`/`efficiency` would inflate every rate on the site by a
number the game does not grant. The implementation plan therefore keeps all five
in config — with the three non-race entries **present and commented as
deliberately unmodelled**, so that a later reader finds a decision rather than an
omission — and pins the rule with a test: *the three non-race shrines never move a
rate at any level* (plan §7.4, new test 8).

A second deliberate choice worth recording: the two live terms arrive as
**separate `MemberBonuses.shrine_speed` / `shrine_efficiency` fields** rather than
being folded into `speed` / `efficiency`. That follows the precedent
`building_levels` already set — the quantity is **guild-wide, not member-owned**,
and the type should say so — and it keeps ~13 tests that reconstruct those sums
term by term passing untouched, including two that assert `efficiency == 0.0`
exactly for Enhancing.

---

## 3. The patch-note cross-check that validates the whole reading

The dump is **pre-patch**, so every number above is a claim about the game *before*
2026-08-11. One patch note closes that gap by itself:

> **VERBATIM**: *"Rare Find 1% → 1.5% per level, Essence Find 2% → 3% per level"*

The pre-patch dump holds, exactly:

| buff | dump value, per level | patch note, "from" | match |
|---|---|---|---|
| `rarity_skilling` / `rarity_combat` → `rare_find` | **0.01** | 1% | ✓ |
| `spirit_skilling` → `essence_find` | **0.02** | 2% | ✓ |

Three things follow, and together they are why the shrine work can proceed on a
pre-patch dump at all:

1. **The notes are talking about these buff values** — the "from" figures match the
   dump to the digit, on two independent buffs, which is not a coincidence.
2. **The in-game rule is confirmed**: `flatBoost + (level−1)·flatBoostLevelBonus =
   per_level × level` is the reading under which "1% per level" and
   `flat 0.01 + 0.01/level` are the same statement. That is the same rule
   `config.py` already relies on for guild buildings.
3. **Force and Tempo were not re-tuned.** The notes re-tune the two *loot* buffs
   and say nothing about efficiency or action speed, so the `0.005/level` figures
   are current. What changed for Force and Tempo is not their magnitude but their
   **applicability**: they now apply inside Trials.

The refreshed dump (Phase 0) should confirm `rare_find → 0.015` and
`essence_find → 0.03` and leave `efficiency` / `action_speed` at `0.005`. If it
does not, this section is the thing that was wrong, and §5's numbers move with it.

---

## 4. Two cost ladders, in two different currencies

**This is the trap in the shrine data, and it is the open question of §6.** A
shrine level and a buff level are priced separately, in unrelated currencies.

### 4.1 Shrine level — priced in GUILD POINTS

`guildShrineDetailMap[*].guildPointCosts`, `maxLevel = 20`. **All five shrines
share one identical ladder** (verified: the five `guildPointCosts` maps are
byte-identical), and it is **exactly double the guild-building ladder** — Guild
Brewery L1 500 → shrine L1 1000, L2 675 → 1350, …, L20 149 725 → 299 450.

Verbatim:

```
1: 1000,  2: 1350,  3: 1800,  4: 2450,  5: 3300,
6: 4500,  7: 6050,  8: 8150,  9: 11050, 10: 14900,
11: 20100, 12: 27150, 13: 36650, 14: 49450, 15: 66800,
16: 90150, 17: 121700, 18: 164300, 19: 221800, 20: 299450
```

Cumulative: **L1–L5 = 9 900**, **L1–L20 = 1 152 100** per shrine (so 19 800 and
2 304 200 for Force + Tempo together — the figures in §5).

### 4.2 Buff level — priced in GUILD TOKENS + GUILD CREDITS

Every `guildBuffDetailMap` entry carries its **own** `levelCosts` map, 1..20, in a
completely different currency: `guildTokenCost` plus a `creditCosts` list of
coloured guild credits. Verbatim, for `force_skilling`:

```jsonc
"1":  { "guildTokenCost": 400,
        "creditCosts": [ {"/items/green_guild_credit": 2000},
                         {"/items/white_guild_credit": 2000},
                         {"/items/purple_guild_credit": 200} ] }
"20": { "guildTokenCost": 30000,
        "creditCosts": [ {"/items/green_guild_credit": 420000},
                         {"/items/white_guild_credit": 420000},
                         {"/items/purple_guild_credit": 42000},
                         {"/items/silver_guild_credit": 17100},
                         {"/items/gold_guild_credit": 6000} ] }
```

(Shown compressed; the real shape is `{"itemHrid": ..., "count": ...}` objects.)

**No part of this model touches guild credits or tokens**, which is why the
guild-credit exchange rework in the same patch is out of scope. The consequence
that *is* in scope: **"the guild has Force at level 1" is ambiguous**, and the two
readings price the multiplier differently. See §6.

---

## 5. What a shrine actually buys: a negative result

**Fixture**: the synthetic 20-strong Foraging party of
`research/partial-tier-credit.md` §3 (levels 130…88, tier 11, margin 10.3%,
`f = 0.228`, credit 1211.40), with Force (efficiency) and/or Tempo (action speed)
applied at `0.005/level`, priced against §4.1's shrine ladder at
`TRIAL_WEEKS_BETWEEN_DRAWS = 2.5` weeks between draws.

| shrine level | `f` | credit points | Δ | cumulative gp | weeks to repay |
|---|---|---|---|---|---|
| none (today, ignoring the live L1s) | 0.228 | 1211.40 | — | — | — |
| L1 Force | 0.235 | 1211.75 | +0.35 | 1 000 | 7 196 |
| L1 Force + L1 Tempo | 0.240 | 1212.01 | +0.61 | 2 000 | 8 233 |
| L5 both | 0.293 | 1214.67 | +3.27 | 19 800 | 15 152 |
| L20 both | 0.493 | 1224.64 | +13.24 | 2 304 200 | 435 239 |

**Two conclusions, and the second is the one to publish.**

**(a) The buffs are real and must be modelled.** Force + Tempo at L1 is **+0.61
points per trial**, and Survey Corps *holds* both at level 1 — so until Phase 3
lands, every rate, tier and margin on the site is understated by that much. Note
the mechanism in the `f` column: the buffs do not usually buy a *tier*, they buy
**progress into the next one**, which under the old step objective was worth
literally nothing and is now worth points. Shrines are only *visible* at all
because of partial credit.

**(b) As an investment they are catastrophic.** Even fully maxed, Force + Tempo
buys **+13.24 points — less than one tier — for 2.3 million guild points**, on a
ladder that is exactly twice the buildings'. Meanwhile a single guild *building*
level grants **+2 skill levels to every member in that skill**
(`research/trial-messages.md:103-130`) and the first Guild Brewery costs **500**.

So the trials page should price shrines **and say plainly that buildings
dominate**. This is a negative result the guild can act on, and one nobody can
currently see: the upgrades table today prints *"No building can buy another tier
this week, at any level"* (`build.py:671`) and stops. Under partial credit every
level buys a measurable number, and the honest table shows the shrine rows losing.

---

## 6. Open question: which ladder drives the multiplier, and what are the live levels?

**WORKING ASSUMPTION** (adopted for Phase 3): the **shrine** level from
`guildBuildingLevelMap` drives the buff magnitude, i.e. Force 1 / Tempo 1 grants
`0.005` efficiency and `0.005` action speed to every member.

The evidence for the level itself is a single capture
(`research/trial-messages.md:154-160`, Survey Corps, `guild_updated`, 2026-07-22):

```jsonc
{ "/guild_buildings/builders_hall": 3, "/guild_buildings/guild_hall": 4,
  "/guild_buildings/skilling_encampment": 1, "/guild_buildings/combat_encampment": 1,
  "/guild_buildings/dojo": 1, "/guild_shrines/force": 1, "/guild_shrines/tempo": 1 }
```

Note where the shrines appear: **inside `guildBuildingLevelMap`**, alongside the
buildings. That is the *shrine* level (§4.1, guild points). The **buff** level
(§4.2, tokens + credits) is **not recorded in any capture this repo holds**, and
nothing in the dump says which of the two the resolved magnitude reads from — or
whether it is `min`, `max` or the product of both.

**Resolution**: the patch's new `[View Buffs]` button, which per the patch notes
splits active guild buffs into Skilling and Combat — i.e. it displays exactly the
resolved magnitudes needed, with no inference. Until then `GUILD_SHRINE_LEVELS` is
a hand-entered config map carrying the caveat `config.py` already carries for
`GUILD_BUILDING_LEVELS`: **one map serves both guilds today, and it must be split
the moment SC and LI diverge.** Two smaller consequences of the same gap:

* `SHRINE_BUFFS_APPLY_IN_TRIALS = False` is the one-line rollback if the shrine
  terms turn out to be wrong or mis-scaled; all-zero levels are equivalent.
* The shipped-config test that pins guild building levels to zero needs a shrine
  analogue — which, exactly like the building one, **will fail the day the
  officers build something.** That is the intended behaviour: a hand-entered
  constant that goes stale silently is worse than a test that shouts.

---

## 7. TODO

- [ ] **Refresh the dump** past `v1.20260715.0` and re-read
      `guildBuffDetailMap` / `guildShrineDetailMap`. Expect `rare_find → 0.015`,
      `essence_find → 0.03`, and `efficiency` / `action_speed` unchanged at
      `0.005` (§3). Anything else invalidates §5.
- [ ] **Read the `[View Buffs]` panel** and record the resolved Skilling buff
      magnitudes for both guilds — the one measurement that closes §6.
- [ ] **Harvest the shrine/buff levels automatically**, or accept that
      `GUILD_SHRINE_LEVELS` goes stale the moment the officers spend points. Same
      standing TODO the guild buildings carry
      (`research/trial-messages.md:347-352`).
- [ ] **Put §5(b) on the page** beside the building upgrades, so "shrines are a
      trap" is a published number rather than a note in a repo.
