# Guild Trials — "Trial Data", "Trial Assignments", and "Loadouts" tabs

Source: Google Sheet `1b5_zID6K4WRaFXnBMJijSEXr_4l2gi40eFKxuvRJQAE` (Milky Way Idle, guilds
**Survey Corps (SC)** and its sister guild **Lactose Intolerant (LI)**). Fetched 2026-07-17 via the
anonymous gviz CSV endpoint. All three tabs returned distinct content (verified by md5), so the
known first-tab-fallback gotcha did not bite.

Caveat on fidelity: gviz CSV exports **cell text only**. Checkboxes come through as
`TRUE`/`FALSE`, but embedded images, in-cell links, and cell formatting are lost. Several
"empty" regions (especially in Loadouts) almost certainly contain images or equipment
screenshots in the real sheet.

---

## 1. Tab: "Trial Data" (results log)

Tiny tab: one header row plus one data row. It is a **results/history log**, one row per trial
cycle, recording for each guild the four skilling trials and two combat trials that came up,
the **tier reached**, and **how many members participated**.

Header structure (columns, grouped):

| Group | Columns |
|---|---|
| SC skilling | `Date`, then 4 × (`Skill`, `Tier`, `Members`) |
| SC combat | 2 × (`Combat` boss, `Tier`, `DPS`, `Healer`, `Tank`, `Others`) |
| LI skilling | `Date`, then 4 × (`Skill`, `Tier`, `Members`) |
| LI combat | 2 × (`Combat` boss, `Tier`, `DPS`, `Healer`, `Tank`, `Others`) |

### Survey Corps — cycle dated 07/13

**Skilling trials (4):**

| Trial | Skill | Tier | Members |
|---|---|---|---|
| 1 | Milking | 11 | 20 |
| 2 | Crafting | 11 | 17 |
| 3 | Brewing | 10 | 19 |
| 4 | Alchemy | 9 | 11 |

**Combat trials (2):**

| Trial | Boss | Tier | DPS | Healer | Tank | Others |
|---|---|---|---|---|---|---|
| 1 | Chameleon | 9 | 25 | 4 | 3 | 4 Regals |
| 2 | Hedgehog | 6 | 17 | 8 | 2 | 3 Regal |

(Note: 25+4+3+4 = 36 for Chameleon — combat trials evidently allow far more than 20 players,
or "Others" overlaps other columns. See ambiguities.)

### Lactose Intolerant — cycle dated 07/14

**Skilling trials (4):**

| Trial | Skill | Tier | Members |
|---|---|---|---|
| 1 | Milking | 9 | 12 |
| 2 | Crafting | 9 | 11 |
| 3 | Brewing | 9 | 12 |
| 4 | Alchemy | 9 | 10 |

**Combat trials (2):**

| Trial | Boss | Tier | DPS | Healer | Tank | Others |
|---|---|---|---|---|---|---|
| 1 | Chameleon | 6 | 16 | 5 | 3 | 1 |
| 2 | Hedgehog | 4 | 11 | 5 | 3 | 0 |

### Reading

- Each cycle has **4 skilling trials + 2 combat trials** per guild (so the "4 random unique
  challenges" model applies to the skilling side; combat trials are a separate pair).
- **Tier** looks like the outcome metric — the highest tier the guild cleared/reached in that
  trial. The stronger guild (SC) hits tiers 9–11 where LI hits 9 on the same skills with fewer
  members, consistent with tier scaling on collective output (workpower × members).
- **Members** = participants actually in that trial (max observed 20 for skilling, matching the
  20-player cap).
- Skills drawn on 07/13–14: Milking, Crafting, Brewing, Alchemy (same 4 for both guilds — the
  random skill draw may be global per cycle, not per guild).
- Combat bosses seen here: Chameleon, Hedgehog. (Loadouts adds Jelly, Badger, Swarm.)

---

## 2. Tab: "Trial Assignments" (current-cycle policy + rosters)

This is the guild's **sign-up policy and role roster** tab, not a per-player skilling
assignment grid. Top-of-tab banner:

> "ALL TRIALS ARE FREE ASSIGNED. You are free to decide which Trial you want to join, however
> do follow the requirements below."

### 2.1 Skill cut-offs

Two columns of per-skill numbers, headed:

- **"Skilling Trails Survey Corps — Cut-Off(30)"**
- **"Lactose Intolerant — Cut-Off(25)"**

| Skill | SC Cut-Off (30) | LI Cut-Off (25) |
|---|---|---|
| Milking | 119 | 112 |
| Foraging | 121 | 117 |
| Woodcutting | 113 | 106 |
| Cheesesmithing | 116 | 107 |
| Crafting | 116 | 112 |
| Tailoring | 113 | 108 |
| Cooking | 121 | 116 |
| Brewing | 118 | 113 |
| Alchemy | 109 | 105 |
| Enhancing | 106 | 101 |

Exactly **10 skills** — the trial-eligible skill list. (No "Bell Farming"; the tenth skill is
Enhancing, and Alchemy is included.)

Interpretation of the cut-offs: they are **minimum skill levels for joining a trial in that
skill**. The parenthetical (30)/(25) most plausibly means the cut-off was set at the skill
level of the guild's **30th (resp. 25th) ranked member** in that skill — i.e. the threshold is
tuned so roughly the top 30/25 members qualify, from which the best ≤20 fill the trial. (SC
cut-offs are uniformly 4–9 levels above LI's, consistent with SC being the stronger/larger
guild using a deeper rank cut.) This rank-based reading is an inference; the sheet never
defines the parenthetical explicitly.

Sign-up rules (verbatim from the tab):

1. "If you meet the Cut-Off, fill up the Skill Trials following the Priority table below."
2. "If you have Skilling Gear for a Skill, you should join even if you do not meet the Cut-Off"
   — i.e. **equipment matters as much as raw level**, supporting the workpower = level ×
   equipment-efficiency model.
3. "If you do not meet either of these requirements, wait for the Trials to fill up first and
   then join the ones that need players."

### 2.2 Current skilling trials and priority

**"Skilling Trial Info — Date: 7/17"** (today's cycle):

| Slot | Skill | Priority |
|---|---|---|
| Trial 1 | Foraging | 4 |
| Trial 2 | Woodcutting | 3 |
| Trial 3 | Alchemy | 2 |
| Trial 4 | Enhancing | 1 |

"Priority goes from 1 -> 4, with 1 being the highest" — so members should fill **Enhancing
first**, then Alchemy, Woodcutting, Foraging. (Plausibly because Enhancing/Alchemy have the
lowest cut-offs / thinnest talent pool, so they need the qualified people most; the sheet does
not state the rationale.)

Note the skill draw changed from the 07/13 cycle (Milking/Crafting/Brewing/Alchemy) to 7/17
(Foraging/Woodcutting/Alchemy/Enhancing) — consistent with 4 skills drawn randomly each cycle.

### 2.3 Combat trials

**"Combat Trail Info — Date: 7/17"**:

| Slot | Boss | Priority note | Team |
|---|---|---|---|
| Trial 1 | Badger | Mage Priority | Team 1 |
| Trial 2 | Swarm | Melee/Range Priority | Team 2 |

Rules (verbatim highlights):

- "These are the fixed members who will be holding special roles."
- "Only these members should be doing these roles, do not equip an Aura you were not told to."
- "For those with assigned roles, fill the checkbox when you've joined your trial."
- "Do not join a Combat Trial if you are lacking gear and levels. Contact an Officer/General if
  you need assistance."
- "YOU MUST HAVE A DEDICATED COMBAT LOADOUT FOR TRIALS"

Four role rosters follow — **SC Team 1, SC Team 2, LI Team 1, LI Team 2** — each with named
players and a TRUE/FALSE joined-checkbox. Special roles per team:

- 5 unlabeled slots at the top (likely core DPS or leads; label lost in export)
- Tank 1–2
- Cursed 1–2 (aura role)
- Regal 1–2 (aura role — matches the "4 Regals"/"3 Regal" Others column in Trial Data)
- Magic Debuff 1–2
- Stab Debuff 1–2
- Healer 1–6

Roster (player, joined?):

| Role | SC Team 1 | SC Team 2 | LI Team 1 | LI Team 2 |
|---|---|---|---|---|
| (slot) | jodend ✓ | IronAcol ✓ | FerrousKyati ✗ | Brannigan ✓ |
| (slot) | Feal ✓ | Maine ✗ | Felisie ✓ | Eni ✓ |
| (slot) | Inst ✓ | Leevi ✗ | Yed ✗ | Allagash ✗ |
| (slot) | Felisie ✓ | Cvelle ✓ | Hoper2 ✗ | dealkAgain ✓ |
| (slot) | Slambity ✗ | LilSlothly ✗ | IronGaud2 ✗ | OchinchinMiruku ✗ |
| Tank 1 | Slambity ✓ | Rikaliapkm ✗ | JoeterJr ✗ | Brannigan ✓ |
| Tank 2 | VirthorIC ✓ | LilSlothly ✗ | IronGaud2 ✗ | gobrr ✗ |
| Cursed 1 | Inst ✓ | Leevi ✗ | Joeterbaby ✗ | Bowcaster ✓ |
| Cursed 2 | IronVoid ✗ | IronOwl ✗ | Yed ✗ | IronKyati ✗ |
| Regal 1 | IronRestore ✗ | WUDITIENIU ✗ | Xannetrine ✗ | ZelRanged ✓ |
| Regal 2 | Mei ✗ | Zelkyle ✗ | Armor ✗ | Xaivaic ✓ |
| Magic Debuff 1 | Aithe ✗ | Swordy ✗ | Gilgamesh ✗ | Jezzan ✗ |
| Magic Debuff 2 | Felisie ✓ | Xannetrine ✗ | Feai ✗ | Yuengling ✗ |
| Stab Debuff 1 | Nidras ✗ | Eucli ✓ | FerrousKyati ✗ | VentIV ✓ |
| Stab Debuff 2 | Patbowl ✓ | Yedic ✗ | – | – |
| Healer 1 | Felisie ✗ | Xannetrine ✗ | Gilgamesh ✗ | Jezzan ✗ |
| Healer 2 | Aithe ✓ | Swordy ✗ | Feai ✓ | Yuengling ✗ |
| Healer 3 | Room7 ✗ | Covudai ✗ | Healcaster ✓ | – |
| Healer 4 | Spirit ✓ | Atka ✗ | – | – |
| Healer 5 | IronFrisk ✗ | ICAjeje ✗ | – | – |
| Healer 6 | Elytra ✗ | steelflob ✗ | – | – |

Extras (SC): Healer — Snebber; Stab Debuff — Joeter.

LI notes: "Due to the large amount of Natures in Lactose Intolerance, I'll let you guys decide
who wants to be a healer instead of Nature DPS." / "Those who sign up as Healer for next cycle
will be locked into this sheet."

### 2.4 Loadouts tab (equipment assumptions)

The Loadouts tab is a build-reference grid split into **Single Target Builds ("For Chameleon,
Jelly and Hedgehog")** and **Multi-Target Builds ("For Badger and Swarm")**, with a section per
role: Tank, Cursed (1 & 2), Regal, Magic Debuff/Healer, Stab Debuff, Healer(Blooming), ALL DPS,
then per DPS style: Smash, Ranged, Water, Nature(Blooming). The actual gear/ability contents
are images and did not survive CSV export; the only text is advice notes:

- Regal: "Use Maelstrom"
- Stab Debuff: "Special Trigger for Puncture: Target Enemy's Puncture Debuff is Inactive"
- Ranged: "Precision will be better if your Attack/Enhancements aren't high, otherwise use
  Steady Shot"
- Water: "Consider bringing Spring if you have it at lvl40+, however Spring is worse damage and
  only a few should be bringing it."
- Nature: "For that one guy with a Blazing Trident, use this but with Fireball"

Nothing here about **skilling** equipment (efficiency gear) — the Loadouts tab is
combat-only.

---

## 3. Interpretation summary

**What defines a trial/challenge (per this sheet):**

- A **skilling trial** = one of 10 skills (Milking, Foraging, Woodcutting, Cheesesmithing,
  Crafting, Tailoring, Cooking, Brewing, Alchemy, Enhancing). Four are drawn per cycle
  (cycles observed 07/13, 07/14, 7/17 — roughly every few days). Up to 20 members join; the
  guild's result is recorded as a **Tier** (observed 9–11).
- A **combat trial** = one of ≥5 bosses (Chameleon, Hedgehog, Jelly, Badger, Swarm). Two run
  per cycle, staffed by pre-assigned role teams (Tank/Cursed/Regal/Magic Debuff/Stab
  Debuff/Healer + DPS); also produces a Tier. Combat headcounts exceed 20 (36 recorded for one
  Chameleon), so the 20 cap seems to be skilling-only, or combat trials have a larger cap.

**How assignments are recorded:** not as a per-player-per-trial grid. Skilling is
"free-assigned" governed by (a) per-skill level cut-offs, (b) a gear override (good skilling
gear beats the cut-off), and (c) a fill-priority ordering over the 4 active trials. Combat uses
fixed named role rosters with joined checkboxes.

**Scoring/points:** the sheet contains **no point formula and no point totals anywhere**. The
only performance record is the achieved Tier per trial plus participant counts. Any
"workpower = level × equipment efficiency" formula is external to this sheet; the sheet only
corroborates that both level (cut-offs) and equipment (gear override rule, dedicated loadouts)
are the inputs the guild optimizes.

**Ambiguities / unknowns (explicit):**

1. **Cut-Off(30)/(25)** parenthetical is undefined in the sheet. Best reading: rank-depth used
   to set the threshold (level of the 30th/25th best member). Alternatives (e.g. "top 30 sign
   up", or a buff/roster size) can't be excluded from this data alone.
2. **Tier semantics** — assumed to be the tier reached/cleared; could instead be the tier the
   trial was *set* at. Not defined in-sheet.
3. **Points → Tier mapping**, tier thresholds, and whether Members count feeds the score are
   all absent.
4. The 5 **unlabeled roster slots** above "Tank 1" in each combat team lost their label in the
   CSV export (probably a merged header, possibly core DPS or trial captains).
5. **Priority rationale** (why Enhancing = 1) is not stated.
6. Loadout gear specifics are images; not recoverable via gviz. A Drive-authenticated export or
   screenshot would be needed to get actual equipment lists.
7. Whether the 4 drawn skills are shared across guilds server-wide (07/13 SC and 07/14 LI drew
   identical skills, suggesting yes) is unconfirmed with only one data row each.

Raw CSVs preserved during research at
`/private/tmp/claude-501/-Users-morgan-pie-guild/9933582d-18f3-4f30-bd04-d012ebf92d26/scratchpad/`
(`trial_data.csv`, `trial_assignments.csv`, `loadouts.csv`) — session-temporary.
