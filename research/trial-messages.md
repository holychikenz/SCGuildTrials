# Milky Way Idle — Guild "Trials" system: real game-server messages

Source: captured websocket logs in
`/Users/morgan/pie/cowstuff/tampermonkey/.captures/wslog-YYYYMMDD.jsonl`
(console-*.jsonl contained no trial references).

Each captured line is a wrapper: `{"t":<ms>,"kind":"ws","sessionId":"...","type":"<T>","payload":{...}}`.
The inner `payload` repeats `type` and carries the real message body.

The capture is single-character (one player, guild id 4 "Survey Corps"), so every
per-party `participantIds` / `progressMap` only ever contains this one character.

## TL;DR

- The mechanic is **workpower-like, confirmed** — identical field family to the labyrinth
  (`targetWorkValue`, `currentWorkValue`, `progressPerAction`, `successRate`, `efficiency`,
  `doubleProgressChance`, `actionTimeMs`), plus trial-specific `tier`, `currentProgress`,
  `timeoutAt`, `currentEnhLevel`, `actionCounter`.
- A guild week ("trial set") is **4 skilling trials + 2 combat trials = 6 challenges**, drawn
  from fixed pools. The "4 unique challenges" in the task description = the **4 skilling
  trials**; there are additionally 2 combat trials.
- Players **sign up** for at most one skilling trial and one combat trial per week
  (`guild_trial_signup_updated`), choosing a loadout and (for combat) a role.
- Each trial is a laddered set of **tiers**; each tier has a larger `targetWorkValue`. A party
  works a tier until `currentWorkValue >= targetWorkValue`, then advances to the next tier.
- Points accrue by highest tier reached and are summed into the guild's `guildPoints`.

## Message types found

| type | role | key location |
|---|---|---|
| `guild_updated` | Guild state + this week's trial set + aggregate trial results | current in July 2026 files |
| `guild_trial_signup_updated` | This character's weekly signup choices | current |
| `new_guild_skilling` | Start-of-tier snapshot of a skilling trial party (workpower fields) | current (July) |
| `guild_skilling_updated` | Per-action update of a skilling trial party (workpower fields) | current (July) |
| `guild_trial_progress` | Older-named equivalent of the skilling workpower snapshot | June 2026 |
| `guild_trial_member_updated` | This member's weekly trial budget + per-trial progress map | June 2026 |
| `guild_battle_updated` | Combat-trial battle state (combat trials run as battles) | June 2026 |
| `guild_characters_updated`, `guild_item_donations_updated` | Guild roster / donations (not trial-specific) | — |

Naming note: the current (July) client uses `new_guild_skilling` / `guild_skilling_updated`;
earlier captures (June 14) used `guild_trial_progress` for the same payload shape. Treat them
as the same message with different `type` labels across game versions.

## Schemas & example payloads

### `guild_updated` — trial set + weekly results
```jsonc
{
  "type": "guild_updated",
  "guild": {
    "id": 4, "name": "Survey Corps", "guildType": "ironcow",
    "level": 125, "experience": 108404315.9,
    "guildPoints": 750,            // current-week points total
    "lifetimeGuildPoints": 7900,   // all-time
    "currentWeekStartAt": "2026-07-17T00:00:00Z",
    "trialScheduleHourOffset": 121,
    "guildTrialScheduleHourOffset": 121,
    "currentTrialsData": "{...escaped JSON...}"   // see below
  },
  "guildWeeklyTrialSet": {
    "skillHrids":  ["/guild_skilling/woodcutting","/guild_skilling/enhancing",
                    "/guild_skilling/foraging","/guild_skilling/alchemy"],   // exactly 4
    "combatHrids": ["/guild_combat/swarm","/guild_combat/badger"]            // exactly 2
  },
  "guildBuildingLevelMap": {
    "/guild_buildings/guild_hall": 3,
    "/guild_buildings/skilling_encampment": 1,
    "/guild_buildings/combat_encampment": 1,
    "/guild_shrines/force": 1, "/guild_shrines/tempo": 1
  }
}
```

`currentTrialsData` (unescaped) — the guild's aggregate result for the current week:
```jsonc
{
  "points": { "/guild_skilling/milking": 300 },   // total points earned per trial
  "skilling": {
    "status": "completed",                          // ""|"in_progress"|"completed"
    "parties": {
      "/guild_skilling/milking": {
        "highestTier": 2,          // highest tier the party cleared
        "budgetRemainingMs": 0,    // per-party time budget left (cap 3_600_000 = 1h)
        "tierStartedAtMs": 1782230408365,
        "done": true
      }
    }
  },
  "combat": {
    "status": "in_progress",
    "parties": {
      "/guild_combat/warden": {
        "highestTier": 0, "budgetRemainingMs": 3600000,
        "tierStartedAtMs": 1782230409468, "done": false
      }
    }
  },
  "cooperativeRewardGranted": false
}
```

### `guild_trial_signup_updated` — this character's weekly picks
```jsonc
{
  "type": "guild_trial_signup_updated",
  "characterId": 117958,
  "signedUpSkillingTrialHrid": "/guild_skilling/woodcutting",  // or "" if none
  "signedUpSkillingLoadoutID": 412504,
  "signedUpCombatTrialHrid": "/guild_combat/swarm",            // or "" if none
  "signedUpCombatLoadoutID": 0,
  "signedUpCombatRoleHrid": "",   // ""|tank|damage_dealer|support
  "signupWeekStartAt": "2026-07-17T00:00:00Z",
  "trialSignupLevels": { "skillingTrialLevel": 113, "combatLevel": 123 }
}
```
Observed signup domains:
- skilling HRIDs: woodcutting, enhancing, foraging, alchemy, brewing, cheesesmithing, crafting, milking, cooking, tailoring
- combat HRIDs: warden, vanguard, chameleon, swarm, hedgehog, badger, jellyfish, magus, deadeye
- combat roles: `tank`, `damage_dealer`, `support`

### `new_guild_skilling` / `guild_skilling_updated` / `guild_trial_progress` — the workpower engine
Start snapshot (`new_guild_skilling`) and per-action delta (`guild_skilling_updated`) share one shape:
```jsonc
{
  "type": "guild_skilling_updated",
  "trialHrid": "/guild_skilling/cheesesmithing",
  "tier": 1,
  "currentProgress": 0.00329,      // fraction toward this tier's target (0..1)
  "participantIds": [28337],       // party member characterIds (only self in capture)
  "successRate": 0.804,            // per-action success (falls as tier rises)
  "efficiency": 0.317,             // character efficiency (extra actions)
  "doubleProgressChance": 0,       // chance an action counts double (labyrinth-style)
  "progressPerAction": 133,        // workpower added per successful action
  "targetLevel": null,
  "actionTimeMs": 4784,            // time per action
  "timeoutAt": "2026-07-17T11:00:06Z",
  "targetWorkValue": 40400,        // work needed to clear this tier
  "currentWorkValue": 133,         // work accumulated so far this tier
  "currentEnhLevel": 0,
  "actionCounter": 1
}
```

Progress relation: `currentProgress ≈ currentWorkValue / targetWorkValue`; a tier clears when
`currentWorkValue >= targetWorkValue`, incrementing `tier` and raising `targetWorkValue`.

### `guild_trial_member_updated` — this member's weekly budget + progress
```jsonc
{
  "type": "guild_trial_member_updated",
  "progressMap": { "/guild_skilling/milking": 1 },  // per-trial completions/participation for this member
  "budgetSecondsRemaining": 6912,
  "budgetSecondsCap": 7200        // 2h total per member per week
}
```

### `guild_battle_updated` — combat trials run as battles
```jsonc
{
  "type": "guild_battle_updated",
  "battleId": 1, "tier": 1,
  "pMap": { "0": { "cHP":1800,"mHP":1800,"cMP":1500,"mMP":1600,
                   "isActive":true,"leftCombat":false,"atkCounter":2,
                   "abilityHrid":"/abilities/berserk","int":274599542,
                   "dmgCounter":0,"critCounter":0 } },
  "mMap": {}   // monster map
}
```
Combat trials are not a work-value grind; they are tiered battles (same `tier` ladder concept,
resolved through the normal battle engine but under a `guild_battle_updated` channel).

## Inferred mechanics

- **Structure per week:** guild is dealt 4 skilling + 2 combat trials (`guildWeeklyTrialSet`).
  Week boundary is `currentWeekStartAt` (UTC midnight); scheduling offset in
  `trialScheduleHourOffset` / `guildTrialScheduleHourOffset`.
- **Signup:** each character picks ≤1 skilling trial and ≤1 combat trial + loadout (+ combat
  role). This is the "no duplicate players across challenges" constraint's client-side face:
  one skilling assignment per player. (Roster/party grouping is server-side; see Not found.)
- **Tier ladder & work value:** each trial is a series of tiers of increasing
  `targetWorkValue`. Observed skilling scaling (per week/version dependent):
  - July, milking: tier1 `40000`, tier2 `44000`, tier3 `48000` (≈ +10% of base per tier)
  - July, cheesesmithing: tier1 `40400`
  - June, milking tier1: `3000` (values were much smaller in the earlier version)
  `successRate` falls as tier rises (milking 0.848 → 0.808 → 0.736 for tiers 1→3) while
  `progressPerAction`/`efficiency` stay character-fixed — i.e. higher tiers imply a higher
  effective skill requirement.
- **Time budgets (two of them):**
  - Per member per week: `budgetSecondsCap = 7200` (2 hours) — total working time a member may
    contribute (`guild_trial_member_updated`).
  - Per party per tier: `budgetRemainingMs` cap `3600000` (1 hour) plus `timeoutAt`
    timestamp — a party has ~1h to clear the current tier before it times out.
- **Points:** `currentTrialsData.points[trialHrid]` is the guild's earned points for that trial,
  driven by `highestTier` reached. Observed: milking tier1 → 200, tier2 → 300 (cumulative);
  these roll up into `guild.guildPoints` (750 this week) and `lifetimeGuildPoints` (7900).
  Exact per-tier point schedule beyond these two data points was not captured.
- **Workpower verdict:** YES — the skilling trial is the same `targetWorkValue` /
  `progressPerAction` / `doubleProgressChance` / `successRate` / `efficiency` / `actionTimeMs`
  model as the labyrinth, just tiered and time-boxed and pointed.

## Not found / could not confirm from these captures

- **20-players-per-challenge cap:** never observed directly — the capture is single-character,
  so `participantIds` and combat `pMap` only ever contain 1 entry. The cap is not stated in any
  captured message.
- **"No duplicate players across challenges" as a server rule:** only implied by the one-skilling
  + one-combat signup shape; no explicit constraint/validation message was captured.
- **Full per-tier points formula / point table:** only milking tier1→200, tier2→300 seen.
- **Roster/assignment message that groups signed-up players into parties:** not present. The
  client sees only its own party membership (`participantIds`), not the full assignment.
- **Combat-trial work/points detail:** combat trials appear as `guild_battle_updated` battles;
  no work-value or per-tier point payload for combat was captured (this player only ran
  skilling trials to completion).
- **Explicit trial-completion / reward-grant message:** not seen as its own type;
  completion is reflected via `currentTrialsData` status/`done` flags and
  `cooperativeRewardGranted`.
- **Trial-specific leaderboard:** `leaderboard_updated` exists but is generic, not trial-scoped.

---

## CORRECTION (from guild leadership, 2026-07-17)

The time budget is **1 hour per trial** (not 1 hour per tier). Within that hour the
party races upward through tiers sequentially, starting at the lowest; the recorded
result is the highest tier reached. Tier targets are therefore consumed
*cumulatively* against the party's one-hour work output:

    tier reached = max t such that sum(targetWorkValue[1..t]) <= (sum of member work rates) * 3600s

The earlier "1h per party per tier" reading of `budgetRemainingMs`/`timeoutAt` was
an over-interpretation from limited samples. The 2h-per-member weekly budget
(`budgetSecondsCap: 7200`) stands, and accommodates one skilling trial (1h) plus
one combat trial.

---

## WORKING ASSUMPTION (adopted 2026-07-17)

Until the empirical curve is harvested (see TODO below), trial tier scaling is
assumed to mirror the labyrinth model:

- **Tier level**: starts at 100, +10 per tier → `tierLevel(t) = 100 + 10*(t-1)`
  (tier 1 = 100, tier 2 = 110, ... tier 11 = 200)
- **Work target per tier** (lab-sim model): `targetWorkValue(t) = tierLevel(t) * 10`
- **Level delta vs tier**: player success modelled as
  `0.8 * (1 + delta*0.005 if delta>=0 else delta*0.01 + successBonus)` with
  `delta = effectiveLevel - tierLevel(t)` (lab-sim constants)
- Cumulative race with TIER-DEPENDENT output (party output is NOT fixed —
  success decays as tier level rises past member levels):
  `rate(m,t) = success(m,t) * (1 + doubleChance) * floor(workPower_m) / actionSeconds_m`
  `timeToClear(t) = targetWorkValue(t) / sum_m rate(m,t)`
  `tier reached = max T with sum_{t=1..T} timeToClear(t) <= 3600s`
- **Headcount penalty**: each player added to a trial raises the required
  workpower by 1%. Adopted as linear scaling on the tier targets:
  `effectiveTarget(t, N) = targetWorkValue(t) * (1 + 0.01 * N)` for a party of N.
  (Alternative compounding reading `* 1.01^N` differs only slightly at N=20:
  1.20 vs 1.22 — confirm which when the empirical harvest runs.)
  Consequence: filling to 20 is no longer automatically optimal. A marginal
  member is net-positive only if their rate exceeds ~1% of the party's total
  output at the tiers being contested — weak stragglers can now actively
  lower the tier reached.
  Consequence: a member's value depends on which tiers the party contests;
  the optimizer must simulate the race per candidate roster (greedy +
  simulation-guided local search), not just sum static scores. Party SIZE is
  now also a decision variable, not a constant.

## TODO

- [ ] **Harvest the empirical tier curve from captures**: sweep all
      `.captures/wslog-*.jsonl` (May–July) for `guild_skilling_updated` /
      `guild_trial_progress` messages; collect every observed
      (skill, tier, targetWorkValue) pair and every (tier, points) pair from
      `guild_updated.currentTrialsData`; fit the curve and REPLACE the working
      assumption above. Known points so far: milking tier1→200pts, tier2→300pts.
