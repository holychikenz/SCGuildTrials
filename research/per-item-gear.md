# Per-item gear from the `gearSeen` union

**Status:** ResearchPack, 2026-09-02. Measured against SC Roster (107 rows) and LI
Roster (111 rows) as harvested on 2026-09-02, and against
`research/item-stats.json` (game version v1.20260715.0).

**Reproduce every table here** with
`.venv/bin/python research/scratch/gear_survey.py`. Each numbered section below
is a section of that script's output; a re-run is how this document is checked
rather than trusted.

---

## 1. What the column is, and why it changes the model

`apps-script/profiles/Code.gs` now writes one extra column at the tail of each
roster tab: `gearSeen`, the **union of every capture** of that member's gear,
keyed on hrid, keeping the higher enhancement level (see that file's
`GEAR_COLUMN` note and `apps-script/profiles/README.md` § "The gear union").
It is the upstream `stableGear` block that
`.claude/plans/roster-as-primary-source-implementation-plan.md` §11.2 named as
"the highest-value remaining work in the whole area", and the reason it was
named so is `config.RISK_SIGMA_SYSTEMATIC`: the unrecorded neck / ring / earring
slots were 0.0081–0.0110 of a ~0.0123 systematic budget, the largest single row
in it, and larger on their own than everything the roster change retired.

Coverage as harvested (§1 of the survey):

| guild | visible | gear-hidden | blank cell |
|---|---|---|---|
| SC | 98 | 9 | 0 |
| LI | 104 | 6 | 1 |

The nine SC hiders are exactly the nine already recorded in
`roster.Provenance.gear_hidden`. Nothing on either tab failed to parse.

## 2. The catalogue is small, bounded, and tiles the ten skills

Of 188 items in `research/item-stats.json`, **122 carry a race-relevant
channel** — one of `<skill>Speed`, `skillingSpeed`, `<skill>Efficiency`,
`skillingEfficiency`, `enhancingSuccess`, `gatheringQuantity`. Eighty of those
are the tools `config.TOOL_STATS` already models. Of the remaining 42 non-tool
items, three are the task badges §2 excludes below, leaving **39 modelled items**
— the whole of this change:

| slot | items | channel |
|---|---|---|
| back | 4 cape families × {plain, ★} | `<skill>Speed`, 2–3 skills each |
| body | 10 tops | `<skill>Efficiency`; **Enhancer's Top is `enhancingSpeed`** |
| legs | 10 bottoms | as above |
| feet | Collector's Boots | milking/foraging/woodcutting efficiency |
| head | Red Culinary Hat | cooking/brewing efficiency |
| off_hand | Eye Watch | cheesesmithing/crafting/tailoring efficiency |
| hands | Enchanted Gloves | alchemy efficiency **and** enhancing speed |
| neck | Necklace of Speed / of Efficiency / Philosopher's | generic `skilling*` |
| ring | Ring of Gathering / Philosopher's Ring | `gatheringQuantity` |
| earrings | Earrings of Gathering / Philosopher's Earrings | `gatheringQuantity` |

Two facts about that table matter for the design:

- **The four "family pieces" tile the ten skills exactly** — 3 + 2 + 3 + 2 — with
  no skill covered twice and none uncovered. So does the set of four cape
  families, and so do the ten tops and ten bottoms. Every skill has exactly one
  covering item per slot, which is what makes a per-skill lookup a total function
  rather than a table with holes.
- **`trinket` and `pouch` are excluded.** The three task badges carry `taskSpeed`
  (the task board, not a trial) and the pouches carry `drinkConcentration`. The
  Guzzling Pouch is the *seventh* most-seen item in the union — 82 members — and
  contributes nothing to a race. Excluding them is the same rule
  `trials.guild_shrine_bonuses` applies to the Rarity, Spirit and Scholar shrines
  and `config.TOOL_STATS` applies to `<skill>RareFind` / `<skill>Experience`.

Eleven race-relevant items have never been observed on either guild: seven
garments (Brewer's/Tailor's/Enhancer's Tops, and five Bottoms), plus the three
task badges. They are modelled anyway — the table comes from the catalogue, not
from what happened to be seen.

## 3. What the model asserts today, against what the union says

| the model's term | today's value | observed |
|---|---|---|
| `CAPE_SPEED_PLUS3`, every member, every skill | 0.0665 speed | 97 capes on 202 members; pooled mean **effective** speed 0.0738; 73% refined; mean level 2.74 against the assumed +3 |
| `ARMOUR_EFFICIENCY_PLUS7`, family piece, unconditional | 0.1182 efficiency | 48% of members show **none** of the four, 37% show **all four**; mean level 4.6–6.3, not 7 |
| `ARMOUR_EFFICIENCY_PLUS7` × top/bot, on the manual tick | 0.1182 each | 45 top and 8 bottom garments seen; ticks are a near-perfect superset of sightings (§5) |
| neck slot | **unmodelled**, priced in σ at 0.0081–0.0110 | 178 of 202 show a necklace: 117 Philosopher's, 57 Speed, 4 Efficiency (and 7 wear Necklace of Wisdom, which is inert in a race) |
| `GEAR_DOUBLE_CHANCE`, every member, gathering only | 0.05 | 95 gathering rings, 101 gathering earrings; 34 wear Rare Find instead |
| `ENHANCEMENT_ASSUMED_LEVEL` on every non-tool piece | 7 | grand mean 5.91 over 1,448 observations; mode 5 |

### 3.1 The family pieces are held all-or-nothing (§4)

This is the measurement that governs the whole design, and it does not say what a
first glance at "49% own boots" suggests:

| of the four pieces | members | share |
|---|---|---|
| 0 | 97 | 48% |
| 1 | 10 | 5% |
| 2 | 4 | 2% |
| 3 | 17 | 8% |
| 4 | 74 | 37% |

Bimodal, not uniform. And the obvious objection — that a capture merely caught
somebody in combat gear — is answered by the neck slot: **82 members wear a
skilling necklace and show not one of the four family pieces.** A member wearing
Philosopher's Necklace was not photographed mid-boss-fight.

The decision taken (§6) nevertheless keeps the universal grant, on the operator's
judgement that the union has not converged and that these pieces are near-
universal in practice. **That judgement is the largest open risk in this change,
and it is recorded here rather than buried:** if it is wrong, roughly half of
both guilds is being credited a 0.1182 efficiency term it does not own, which is
the single largest mispricing in the model. It is also cheap to revisit — flip
`GEAR_IMPUTE_FAMILY_PIECE` to False and the evidence-led reading is restored in
one line. Re-run §4 once the union has had a few more weeks to accumulate: if the
"0 of four" column has not shrunk, the bimodality is real ownership and the
switch should move.

### 3.2 Slot multiplicity: the union has not yet accumulated (§3)

**No member shows two race-relevant items in any one slot** — every slot is 0 or
1 across all 202 visible members. The captures are, effectively, one snapshot
each. The best-in-slot rule (§6) is therefore correct and currently dormant; it
is implemented for when the union does begin to hold two.

### 3.3 The manual tick is a superset of the sighting (§5)

Pooled over both guilds, per (member, skill):

| | union sees it | union does not |
|---|---|---|
| top ticked | 45 | 126 |
| top **not** ticked | **3** | 1,796 |
| bot ticked | 8 | 22 |
| bot **not** ticked | **1** | 1,939 |

Four cases in 1,900 where the union saw a garment nobody ticked. The tick is
therefore the *ownership* claim and the union is the *level* source that lags
behind it — which is exactly the rule §6 adopts. The four exceptions are
ownership the officers' tab missed, and are taken as owned.

### 3.4 The tool columns are corroborated exactly (§6 of the survey)

**2,020 of 2,020** tool observations agree between the roster's existing
`tool_*` / `tool_*Enh` snapshot columns and the union: same item, same
enhancement level, no blanks, no mismatches. Two consequences:

- The tool path needs no change whatsoever, and this ResearchPack proposes none.
- `config.TOOL_ENHANCE_WHEN_UNKNOWN = 0` is now confirmed never exercised on
  live data, closing the handover note's fourth follow-up: not merely
  "zero observations" but zero out of 2,020 with an independent source agreeing
  on every one.

It also validates the union's writer end to end. Two independently-derived views
of the same 2,020 facts agreeing exactly is the strongest evidence available that
`mergeGear_` and the userscript are correct.

## 4. `gatheringQuantity` inherits an open question; it does not create one

`config.py` §1177 already records that the game's `/buff_types/gathering`
("increases gathering quantity") is a **different buff type** from the
`doubleProgressChance` field this model drives it through, and `build.py`:2639
already says so on the page. `GEAR_DOUBLE_CHANCE = 0.05` is the "working
assumption ... pending the per-member gear harvest"; the harvest has arrived, and
it replaces a flat 0.05 with the ring and earrings each member actually wears.

The channel question is untouched by that and remains open. What changes is that
it is now *isolable*: `GEAR_GATHERING_IN_RATE = False` prices every
`gatheringQuantity` item at zero in one line, which the flat constant could not
do without also removing the community buff.

## 5. Variance in enhancement level: who, and which

Over 1,448 race-relevant observations, grand mean level 5.91:

- **34.1%** of the variance is explained by *which member* it is;
- **31.5%** by *which item* it is.

Near-equal. A member's per-item mean level runs from 2.00 to 8.62 (sd 1.30) and
the median within-member spread is 6 levels. So neither a per-item mean nor a
per-member mean captures more than about a third of the signal, and an additive
member+item fit would capture most of both.

**The decision (§6) is the per-item mean anyway.** The additive fit was offered
and declined, and the reason to record the measurement rather than the regret is
that it bounds what is being given up: roughly a third of the explainable
variance in a term that is itself a second-order correction on an item's base
stat. It is a candidate for a later pass, not a defect in this one.

## 6. The rules, as decided

Per member, per skill, for each race-relevant slot:

**§6.1 Observed in the union** → price at the observed enhancement level. Where
two items are seen in one slot, the **best** wins (Philosopher's over the
single-stat alternatives). Currently dormant — see §3.2. *(The imputation
statistics have their own subsection at §6.7, below.)*

**§6.2 Not observed:**

- **Tools** — unchanged. The existing `tool_*` columns, which agree 2,020/2,020.
- **Cape** — assume the skill's covering cape at the guild's **pooled mean
  effective speed**, including for a member observed wearing a *different*
  family's cape on a skill that cape does not cover. One slot can only ever show
  the one worn, so a sighting says nothing about the other three families. The
  same applies to a member seen in a non-cape back item (an Enchanted Cloak, 15
  members), which is the cape's analogue of the Necklace-of-Wisdom case in §6.5
  and is deliberately resolved the *other* way.
- **Family piece** — assume owned, at that item's **per-guild mean level**.
- **Top / bottoms** — owned iff the manual checkbox is ticked **or** the union
  saw it. Level: observed where seen, else the guild's **pooled garment mean
  level**. Neither ticked nor seen → no garment.
- **Neck / ring / earrings** — **zero. Never imputed.** The Philosopher's pieces
  are the rarest items in the game and must not be assumed.

**§6.3 Gear-hidden members are not a special case.** They follow the unobserved
rules exactly — imputed cape and family piece, no accessories, garments on the
tick alone. There is no `hidden` branch anywhere in the design, which is the
single largest simplification in it.

**§6.4 Channels follow the catalogue exactly.** Enhancer's Top and Bottoms grant
`enhancingSpeed`, retiring the uniform-efficiency simplification
`trials.member_bonuses` documents today; the generic `skillingSpeed` and
`skillingEfficiency` reach enhancing as they reach any skilling action. That last
is the reading of an **unverified generic** — the catalogue says "applies to all
skilling actions" and enhancing is a skilling action, but no capture confirms it.
It affects the 117 members wearing a Philosopher's Necklace and is isolable to one
row of `gear.STAT_CHANNELS` if a capture ever refutes it.

**§6.5 An inert item in a slot needs no branch.** A member wearing Necklace of
Wisdom or Ring of Rare Find has no race-relevant item in that slot, and §6.2's
accessory case scores it zero already. This falls out of the design rather than
being coded into it.

**§6.6** `RISK_SIGMA_SYSTEMATIC` is recalibrated within this change, as phase R6
did for the roster.

### 6.7 Why three imputation statistics and not one

The per-item mean is the decided rule, but for the garments it cannot be
computed: eight of the eleven observed garment items rest on **n = 1 or n = 2**,
and a mean of one observation is not a mean. The capes are pooled because the
operator's rule named them so. Hence three statistics, each with adequate
support, each **per guild** — the guilds differ by 1.2–1.5 enhancement levels on
the family pieces, so pooling them would misprice both:

| statistic | scope | SC | LI |
|---|---|---|---|
| cape mean **effective speed** | pooled over all 8 cape items | 0.075315 (n=51) | 0.072070 (n=46) |
| Collector's Boots mean level | per item | 6.300000 (n=50) | 4.795918 (n=49) |
| Red Culinary Hat mean level | per item | 6.195652 (n=46) | 4.822222 (n=45) |
| Eye Watch mean level | per item | 5.936170 (n=47) | 5.065217 (n=46) |
| Enchanted Gloves mean level | per item | 5.659091 (n=44) | 4.605263 (n=38) |
| garment mean level | pooled over all body+legs | 5.333333 (n=33) | 4.916667 (n=24) |

**Computed at build time, not transcribed.** Unlike `TOOL_STATS` and
`ENHANCEMENT_MULT_TABLE` — catalogue facts, which are pinned as constants and
tested against the JSON — these are *live measurements of a changing guild*, and
a transcribed value would be stale the week after it was written. The figures
above are the values as of 2026-09-02, recorded so a drift can be noticed.

Note the cape statistic is a mean of **effective bonuses**, not of levels. Pooling
the levels would then have to pick a base to apply them to, and the plain/★ split
(0.05 against 0.058, at 73% refined) makes that choice arbitrary; pooling the
finished bonus does not.

## 7. Expected direction of the change

Not all one way, which is the reason to measure rather than argue:

| term | direction | rough size |
|---|---|---|
| neck slot, newly observed for 88% | **up** | new `skillingSpeed` 0.04–0.067 and `skillingEfficiency` 0.02–0.033 where seen |
| cape, 0.0665 → 0.0738 pooled mean | **up** | +11% on the cape term for every unobserved member |
| family piece, +7 → observed/mean level | **down** | mult 9.1 → ~5.9 (SC) / ~4.6 (LI), i.e. 0.1182 → ~0.107 / ~0.102 |
| ring + earrings, flat 0.05 → observed | **down for ~half** | 0.05 → ~0.053 where both are worn, 0 where neither is |
| Enhancer's garments, efficiency → speed | **channel change** | affects only the 4 members who own them |
| garments, +7 → observed or pooled mean | **down** | mult 9.1 → ~5.3 (SC) / ~4.9 (LI) |

`RISK_SIGMA_SYSTEMATIC` should **fall**, but not to zero, and not by the whole
0.0081–0.0110 neck row: the 24 members with no necklace observed and the 16 who
hide their gear keep that uncertainty in full, and the imputed family piece and
cape introduce a *new* uncertainty the previous σ did not carry — the imputation
error itself. A σ near zero here would be a bug, exactly as it would have been in
the roster change.

### 7.1 MEASURED, phase G6 (2026-09-02)

Full output: `research/gear-reconciliation-2026-09-02.txt`; harness:
`research/scratch/gear_reconcile.py`. Each slice is priced by RE-SCORING the
baseline lineup, so the repricing is isolated from the search's response to it;
the last row runs a fresh search, which is what the flip actually publishes.
This week's live draw (C.Smithing, Milking, Enhancing, Tailoring), seed 1234.

| slice | predicted | SC Δcredit | SC ΔE | LI Δcredit | LI ΔE |
|---|---|---|---|---|---|
| cape | **up** | +1.57 | +1.89 | +1.23 | +1.44 |
| family piece | **down** | −0.50 | −0.79 | −1.72 | −2.00 |
| garments | **down** | −1.19 | −2.11 | −0.06 | −0.06 |
| accessories | **up**, dominant | **+10.40** | **+11.12** | **+10.45** | **+11.23** |
| all four, frozen lineup | net up | +10.14 | +10.86 | +9.79 | +10.57 |
| **re-optimised** | | **+13.64** | **+14.01** | **+12.06** | **+12.55** |

**Every slice moved in its predicted direction on both guilds.** Three further
things the table says that §7's per-term reasoning could not:

- **The accessories carry the whole change, and the two guilds agree to within
  0.05** (+10.40 against +10.45) — two rosters of different size, level and wealth
  putting almost exactly the same value on reading the neck slot. That agreement is
  what makes the term credible as a property of the game rather than of one guild's
  data.
- **Re-optimising gains a further ~3 points beyond the repricing** (+13.64 against
  +10.14 on the frozen lineup). Better information does not merely re-score the
  same plan; the search finds a better one. Every trial's progress into its next
  tier rises — Tailoring's from 0.1034 to 0.3061 on SC, Enhancing's from 0.3294 to
  0.5116 on LI.
- **STEP POINTS DO NOT MOVE**: 4900 and 4600, before and after, on both guilds. The
  gain is entirely in partial credit and in safety. The thinnest trial goes from
  P = 0.9908 to 1.0000 on SC (0.9854 → 1.0000 on LI) when the lineup is frozen, and
  settles at 0.9945 / 0.9938 once the search is allowed to spend a sliver of
  certainty for expected points — which is `OPT_OBJECTIVE = "expected"` behaving as
  designed, and still above both baselines.

**A WARNING FOR ANYONE RE-RUNNING THIS.** The first three attempts at this table
were WRONG, and one of them was wrong with a plausible-looking answer of the
opposite sign (−5 rather than +11). The causes are recorded in the plan's §5b.1;
the short version is that two were defects in the *switched-off* path and one was
a harness that loaded its members before enabling the parse, so it measured a
guild wearing nothing. If a slice row ever reads exactly `+0.00`, or if three
slices of visibly different size report the same number, suspect the harness
before believing the result.

## 8. What this does not do

- **Combat gear is ignored.** The union carries it (Chaotic Flail, Anchorbound
  Plate, and 60-odd more), none of it has a race-relevant channel, and none of it
  is read.
- **The `pouch` and `trinket` slots are not modelled** (§2).
- **The additive member+item imputation is not built** (§5).
- **No page yet reports per-member gear.** Provenance counters are extended;
  a per-member gear badge is a follow-up.
- **`GEAR_DOUBLE_CHANCE`'s channel question is not resolved** (§4).
