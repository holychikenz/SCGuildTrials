# Community buffs: five buffs, a 1..20 ladder, and one assumption worth 16% of every gathering rate

**Status**: the buff **magnitudes and their level ladders are CONFIRMED game data**,
read directly from the client dump. What is **NOT** confirmed is (a) the guild's
live buff **levels** — no capture this repo holds records them, exactly the gap
`research/guild-shrines.md` §6 carries for the shrines — and (b) whether the
gathering buff reaches the trial race at all, which is §3 and by far the most
expensive open question in the model.

**Source**: `/Users/morgan/pie/cowstuff/milkyway_client_info.json`,
`gameVersion v1.20260715.0`, `versionTimestamp 2026-07-16T03:24:51Z`. Key read:
`communityBuffTypeDetailMap` (5 entries). **This dump predates the 2026-08-11
patch**; refreshing it is a standing TODO shared with the shrine note.

**Why this note exists**: the three community buffs this model applies were
hard-coded as flat placeholders (`0.20` / `0.15` / `0.20`) flagged *WORKING
ASSUMPTION (2026-07-17)*. They are not assumptions at all — they are in the dump,
they are **levelled**, and one of the three numbers was not a value the game
grants at any level.

---

## 1. The five buffs, and the three that matter here

Each `communityBuffTypeDetailMap` entry is bought with **cowbells**, carries a
`usableInActionTypeMap` naming the action types it applies to, and a single `buff`
whose `typeHrid` says what it does.

| hrid | `typeHrid` | flat + per level | cowbells | enters the race? |
|---|---|---|---|---|
| `gathering_quantity` | `/buff_types/gathering` | **0.20 + 0.005/level** | 10 | **YES** (see §3) |
| `enhancing_speed` | `/buff_types/action_speed` | **0.20 + 0.005/level** | 10 | **YES** → `action_seconds` |
| `production_efficiency` | `/buff_types/efficiency` | **0.14 + 0.003/level** | 10 | **YES** → `work_power` |
| `experience` | `/buff_types/wisdom` | 0.20 + 0.005/level | 20 | no — **XP** |
| `combat_drop_quantity` | `/buff_types/combat_drop_quantity` | 0.20 + 0.005/level | 10 | no — **combat loot** |

The last two are **deliberately unmodelled**, for precisely the reason
`guild-shrines.md` §2 gives for Rarity / Spirit / Scholar: `wisdom` changes XP,
which the race never reads, and combat drops are not in a `targetWorkValue` grind.
They are recorded here so a later reader finds a decision rather than an omission.

`usableInActionTypeMap` is worth noting for the way it partitions the skills, and it
matches `config.GATHERING_SKILLS` and the production family exactly:

* `gathering_quantity` → milking, foraging, woodcutting.
* `production_efficiency` → cheesesmithing, crafting, tailoring, cooking, brewing,
  **alchemy** (so the trial skill "Alchemy", the guild's "Bell Farming" column, is
  production — as `config` already assumed).
* `enhancing_speed` → enhancing.

A verbatim entry, so the shape is auditable:

```jsonc
{
  "hrid": "/community_buff_types/production_efficiency",
  "name": "Production Efficiency",
  "usableInActionTypeMap": {
    "/action_types/alchemy": true, "/action_types/brewing": true,
    "/action_types/cheesesmithing": true, "/action_types/cooking": true,
    "/action_types/crafting": true, "/action_types/tailoring": true
  },
  "buff": {
    "uniqueHrid": "/buff_uniques/production_community_buff",
    "typeHrid": "/buff_types/efficiency",
    "ratioBoost": 0, "ratioBoostLevelBonus": 0,
    "flatBoost": 0.14, "flatBoostLevelBonus": 0.003,
    "startTime": "0001-01-01T00:00:00Z", "duration": 0
  },
  "cowbellCost": 10, "sortIndex": 3
}
```

---

## 2. The scaling rule, and the trap in it

The magnitude follows the same in-game rule the buildings, houses and shrines use:

```
value(level) = flatBoost + (level - 1) * flatBoostLevelBonus       # level 1..20
```

**The trap**: for buildings, house rooms and shrines `flatBoost ==
flatBoostLevelBonus`, which collapses the rule to `per_level * level` — and
`config.py` leans on that shortcut in three places for exactly those three things
(`HOUSE_EFFICIENCY_PER_LEVEL`, the building `+2/level`, the shrine `0.005/level`).
**Community buffs break that equality.** They open at a large base and then creep:

| level | gathering | enhancing speed | production efficiency |
|---|---|---|---|
| **1** | **0.200** | **0.200** | **0.140** |
| 2 | 0.205 | 0.205 | 0.143 |
| 5 | 0.220 | 0.220 | 0.152 |
| 10 | 0.245 | 0.245 | 0.167 |
| 15 | 0.270 | 0.270 | 0.182 |
| **20** | **0.295** | **0.295** | **0.197** |

Extending the shortcut here would be badly wrong in both directions — it would claim
`0.005 × 1 = 0.005` at level 1 (a fortieth of the truth) and `0.10` at level 20 (a
third of it). `config.COMMUNITY_BUFF_LADDER` therefore stores `(flatBoost,
flatBoostLevelBonus)` as a pair and `trials.community_buff_value()` applies the full
rule, with the "not the shortcut" case pinned by a test.

### What this corrected

| constant | was | now (level 1) | note |
|---|---|---|---|
| `COMMUNITY_GATHERING_BUFF_DOUBLE` | 0.20 | 0.20 | correct, but by luck — it was the level-1 value with no level recorded |
| `COMMUNITY_ENHANCING_SPEED_BUFF` | 0.20 | 0.20 | as above |
| `COMMUNITY_PRODUCTION_EFFICIENCY_BUFF` | **0.15** | **0.14** | **0.15 is not attainable at any level**: the ladder passes 0.149 at L4 and 0.152 at L5, so 0.15 would need level 4.33 |

So the shipped model was implicitly assuming level 1 for two buffs and level ~4½ for
the third. Level **1** is now the single published default (`COMMUNITY_BUFF_LEVEL`),
and the trials page carries a **level-20 counterfactual** built by a second full
optimiser run under `trials.community_buff_level(20)` — a switch at the top of the
page, not a change of default, because the guild's real levels are unknown.

The counterfactual is a *second whole optimisation*, not this week's parties re-rated.
That is deliberate: a community buff is **common-mode** — one draw applied to every
member of the party, undiluted by party size (`calibrate.py`'s note on why buff
uncertainty outweighs gear uncertainty point for point) — so raising it changes which
members are worth seating, not merely how fast the seated ones work.

---

## 3. OPEN QUESTION: is the gathering buff in the race at all?

**This is the most expensive unresolved question in the rate model.**

The model applies the gathering buff as the engine's `doubleProgressChance`: the
chance an action counts double, scaling a member's rate by `(1 + doubleChance)` per
the lab-sim formula (`trial-messages.md` §"lab-sim model"). But the dump types the
two things **separately**:

| type | dump description |
|---|---|
| `/buff_types/gathering` | *"Increases gathering **quantity**"* ← what the community buff grants |
| `/buff_types/labyrinth_double_progress` | *"Chance to **double progress** in labyrinth skilling rooms"* ← what `doubleProgressChance` reports |

Gathering *quantity* governs **what drops**, not how fast `targetWorkValue`
accumulates. That is the identical distinction `guild-shrines.md` §2 enforces as a
hard rule when it bars `rare_find` and `essence_find` from the rate model. Applied
consistently, that rule says the community **gathering** buff should not touch the
rate model either — and `DOUBLE_CHANCE` would fall from 0.25 to the 0.05 gear
placeholder, taking **~16% off every gathering party's rate** — equivalently, the
rates published today would be ~19% too high. (`calibrate.scenario_buffs_lapsed`
already prices exactly this step, as a regime rather than a sigma.)

Arguing the other way: trials are confirmed to share the labyrinth's whole field
family (`trial-messages.md:15-17`), the trial engine *does* expose a
`doubleProgressChance` field, and a gathering trial's work is plausibly counted in
units harvested — in which case quantity and progress genuinely coincide and the
current model is right.

**The evidence held today does not settle it.** The one capture in the repo shows
`doubleProgressChance: 0` on a **cheesesmithing** trial, which is consistent with
either reading (production gets no such buff under either).

**Resolution — one measurement**: a `guild_skilling_updated` / `new_guild_skilling`
capture from a **gathering** trial (Milking / Foraging / Woodcutting) taken **while
the community gathering buff is live**. If `doubleProgressChance` is non-zero there,
the model is vindicated and the value also calibrates `GEAR_DOUBLE_CHANCE` for free.
If it is `0`, `trials.double_chance()` must be excised and every gathering figure on
the site re-based.

Until then the assumption stays — it is the status quo, and flipping it on semantics
alone would be trading a documented guess for an undocumented one — but it is now
stated on the page in those terms rather than buried as a placeholder.

---

## 4. TODO

- [ ] **The gathering capture** (§3). The single highest-value measurement
      outstanding anywhere in this model.
- [ ] **Refresh the dump** past `v1.20260715.0` and re-read
      `communityBuffTypeDetailMap`. The 2026-08-11 patch re-tuned two *shrine* loot
      buffs (`guild-shrines.md` §3); nothing in the notes touches these five, so
      expect no change — but the ladder is now load-bearing in two places.
- [ ] **Record the guild's real buff levels** from the patch's `[View Buffs]` panel,
      which displays resolved Skilling buff magnitudes with no inference needed. The
      same measurement that closes `guild-shrines.md` §6, and it would replace
      `COMMUNITY_BUFF_LEVEL = 1` with the truth.
- [ ] **Price the ladder.** `cowbellCost` is per level in the dump, so
      "what does one more level of the production buff buy the guild, and at what
      cowbell cost?" is answerable in the same shape as the shrine payback table —
      and, given the creep is only `0.003`/level, likely another negative result
      worth publishing.
