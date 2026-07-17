# Milky Way Idle — Skilling Equipment Stat Tables

Source: `wslog-20260717.jsonl` `init_client_data` payload. Game version **v1.20260715.0** (versionTimestamp 2026-07-16T03:24:51.335088932Z).

Machine-readable companion: `item-stats.json` (188 equipment items with non-empty noncombat stats).

## 1. Enhancement scaling

The client ships a single `enhancementLevelTotalBonusMultiplierTable` (21 entries, indexed by enhancement level 0–20). It multiplies the per-level *enhancement bonus* and is added on top of the base stat. There is no separate noncombat table — the same multiplier governs both `combatEnhancementBonuses` and `noncombatEnhancementBonuses`.

**Formula (confirmed by field layout):**

```
effectiveStat = noncombatStats[field] + enhancementLevelTotalBonusMultiplierTable[level] * noncombatEnhancementBonuses[field]
```

At level 0 the multiplier is 0, so an unenhanced item yields exactly its base `noncombatStats`. This matches the observed table (index 0 = 0, index 1 = 1).

| Level | Multiplier | | Level | Multiplier |
|------:|-----------:|---|------:|-----------:|
| +0 | 0 | | +10 | 14.500000000000002 |
| +1 | 1 | | +11 | 16.7 |
| +2 | 2.1 | | +12 | 19.2 |
| +3 | 3.3 | | +13 | 22 |
| +4 | 4.6 | | +14 | 25.1 |
| +5 | 6 | | +15 | 28.5 |
| +6 | 7.5 | | +16 | 32.2 |
| +7 | 9.1 | | +17 | 36.2 |
| +8 | 10.8 | | +18 | 40.50000000000001 |
| +9 | 12.600000000000001 | | +19 | 45.1 |
| +10 | 14.500000000000002 | | +20 | 50 |

Key values: **+7 → 9.1×**, +8 → 10.8×, +10 → 14.5×, +20 → 50×.

`enhancementLevelSuccessRateTable` (base per-attempt success, 20 entries starting at +1→+20): [0.5, 0.45, 0.45, 0.4, 0.4, 0.4, 0.35, 0.35, 0.35, 0.35, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]

## 2. Skilling tools (Holy vs Celestial)

Each skill has one tool equipment type. Holy is the tier-80 top f2p/craftable tool; Celestial is the tier-90 tool and additionally carries RareFind + Experience stats.

### Holy tools

| Item | hrid | Slot | Lvl req | Base noncombatStats | Enhancement bonus /level |
|------|------|------|---------|---------------------|--------------------------|
| Holy Brush | `/items/holy_brush` | milking_tool | milking 80 | milkingSpeed=0.9 | milkingSpeed=0.018000000000000002 |
| Holy Shears | `/items/holy_shears` | foraging_tool | foraging 80 | foragingSpeed=0.9 | foragingSpeed=0.018000000000000002 |
| Holy Hatchet | `/items/holy_hatchet` | woodcutting_tool | woodcutting 80 | woodcuttingSpeed=0.9 | woodcuttingSpeed=0.018000000000000002 |
| Holy Hammer | `/items/holy_hammer` | cheesesmithing_tool | cheesesmithing 80 | cheesesmithingSpeed=0.9 | cheesesmithingSpeed=0.018000000000000002 |
| Holy Chisel | `/items/holy_chisel` | crafting_tool | crafting 80 | craftingSpeed=0.9 | craftingSpeed=0.018000000000000002 |
| Holy Needle | `/items/holy_needle` | tailoring_tool | tailoring 80 | tailoringSpeed=0.9 | tailoringSpeed=0.018000000000000002 |
| Holy Spatula | `/items/holy_spatula` | cooking_tool | cooking 80 | cookingSpeed=0.9 | cookingSpeed=0.018000000000000002 |
| Holy Pot | `/items/holy_pot` | brewing_tool | brewing 80 | brewingSpeed=0.9 | brewingSpeed=0.018000000000000002 |
| Holy Alembic | `/items/holy_alembic` | alchemy_tool | alchemy 80 | alchemySpeed=0.9 | alchemySpeed=0.018000000000000002 |
| Holy Enhancer | `/items/holy_enhancer` | enhancing_tool | enhancing 80 | enhancingSuccess=0.036 | enhancingSuccess=0.0007199999999999999 |

### Celestial tools

| Item | hrid | Slot | Lvl req | Base noncombatStats | Enhancement bonus /level |
|------|------|------|---------|---------------------|--------------------------|
| Celestial Brush | `/items/celestial_brush` | milking_tool | milking 90 | milkingSpeed=1.05; milkingRareFind=0.15; milkingExperience=0.04 | milkingSpeed=0.021; milkingRareFind=0.003; milkingExperience=0.0008 |
| Celestial Shears | `/items/celestial_shears` | foraging_tool | foraging 90 | foragingSpeed=1.05; foragingRareFind=0.15; foragingExperience=0.04 | foragingSpeed=0.021; foragingRareFind=0.003; foragingExperience=0.0008 |
| Celestial Hatchet | `/items/celestial_hatchet` | woodcutting_tool | woodcutting 90 | woodcuttingSpeed=1.05; woodcuttingRareFind=0.15; woodcuttingExperience=0.04 | woodcuttingSpeed=0.021; woodcuttingRareFind=0.003; woodcuttingExperience=0.0008 |
| Celestial Hammer | `/items/celestial_hammer` | cheesesmithing_tool | cheesesmithing 90 | cheesesmithingSpeed=1.05; cheesesmithingRareFind=0.15; cheesesmithingExperience=0.04 | cheesesmithingSpeed=0.021; cheesesmithingRareFind=0.003; cheesesmithingExperience=0.0008 |
| Celestial Chisel | `/items/celestial_chisel` | crafting_tool | crafting 90 | craftingSpeed=1.05; craftingRareFind=0.15; craftingExperience=0.04 | craftingSpeed=0.021; craftingRareFind=0.003; craftingExperience=0.0008 |
| Celestial Needle | `/items/celestial_needle` | tailoring_tool | tailoring 90 | tailoringSpeed=1.05; tailoringRareFind=0.15; tailoringExperience=0.04 | tailoringSpeed=0.021; tailoringRareFind=0.003; tailoringExperience=0.0008 |
| Celestial Spatula | `/items/celestial_spatula` | cooking_tool | cooking 90 | cookingSpeed=1.05; cookingRareFind=0.15; cookingExperience=0.04 | cookingSpeed=0.021; cookingRareFind=0.003; cookingExperience=0.0008 |
| Celestial Pot | `/items/celestial_pot` | brewing_tool | brewing 90 | brewingSpeed=1.05; brewingRareFind=0.15; brewingExperience=0.04 | brewingSpeed=0.021; brewingRareFind=0.003; brewingExperience=0.0008 |
| Celestial Alembic | `/items/celestial_alembic` | alchemy_tool | alchemy 90 | alchemySpeed=1.05; alchemyRareFind=0.15; alchemyExperience=0.04 | alchemySpeed=0.021; alchemyRareFind=0.003; alchemyExperience=0.0008 |
| Celestial Enhancer | `/items/celestial_enhancer` | enhancing_tool | enhancing 90 | enhancingSuccess=0.042; enhancingRareFind=0.15; enhancingExperience=0.04 | enhancingSuccess=0.00084; enhancingRareFind=0.003; enhancingExperience=0.0008 |

Note: all Holy tools give **+0.9 speed** (0.018/level) except **Holy Enhancer** which gives **+0.036 enhancingSuccess** (0.00072/level). All Celestial tools give **+1.05 speed / +0.15 RareFind / +0.04 Experience** (0.021 / 0.003 / 0.0008 per level) except **Celestial Enhancer** = **+0.042 enhancingSuccess / +0.15 RareFind / +0.04 Experience** (0.00084 / 0.003 / 0.0008 per level).

## 3. Skilling armour

### Tops (body slot) — "skilling top"

Each gives Efficiency 0.1 (0.002/lvl) + RareFind 0.15 (0.003/lvl) for its skill. Enhancer's Top gives enhancingSpeed instead of efficiency.

| Item | hrid | Slot | Lvl req | Base noncombatStats | Enhancement bonus /level |
|------|------|------|---------|---------------------|--------------------------|
| Dairyhand's Top | `/items/dairyhands_top` | body | milking 90 | milkingEfficiency=0.1; milkingRareFind=0.15 | milkingEfficiency=0.002; milkingRareFind=0.003 |
| Forager's Top | `/items/foragers_top` | body | foraging 90 | foragingEfficiency=0.1; foragingRareFind=0.15 | foragingEfficiency=0.002; foragingRareFind=0.003 |
| Lumberjack's Top | `/items/lumberjacks_top` | body | woodcutting 90 | woodcuttingEfficiency=0.1; woodcuttingRareFind=0.15 | woodcuttingEfficiency=0.002; woodcuttingRareFind=0.003 |
| Cheesemaker's Top | `/items/cheesemakers_top` | body | cheesesmithing 90 | cheesesmithingEfficiency=0.1; cheesesmithingRareFind=0.15 | cheesesmithingEfficiency=0.002; cheesesmithingRareFind=0.003 |
| Crafter's Top | `/items/crafters_top` | body | crafting 90 | craftingEfficiency=0.1; craftingRareFind=0.15 | craftingEfficiency=0.002; craftingRareFind=0.003 |
| Tailor's Top | `/items/tailors_top` | body | tailoring 90 | tailoringEfficiency=0.1; tailoringRareFind=0.15 | tailoringEfficiency=0.002; tailoringRareFind=0.003 |
| Chef's Top | `/items/chefs_top` | body | cooking 90 | cookingEfficiency=0.1; cookingRareFind=0.15 | cookingEfficiency=0.002; cookingRareFind=0.003 |
| Brewer's Top | `/items/brewers_top` | body | brewing 90 | brewingEfficiency=0.1; brewingRareFind=0.15 | brewingEfficiency=0.002; brewingRareFind=0.003 |
| Alchemist's Top | `/items/alchemists_top` | body | alchemy 90 | alchemyEfficiency=0.1; alchemyRareFind=0.15 | alchemyEfficiency=0.002; alchemyRareFind=0.003 |
| Enhancer's Top | `/items/enhancers_top` | body | enhancing 90 | enhancingSpeed=0.1; enhancingRareFind=0.15 | enhancingSpeed=0.002; enhancingRareFind=0.003 |

### Bottoms (legs slot) — "skilling bottom"

Each gives Efficiency 0.1 (0.002/lvl) + Experience 0.04 (0.0008/lvl). Enhancer's Bottoms gives enhancingSpeed instead of efficiency.

| Item | hrid | Slot | Lvl req | Base noncombatStats | Enhancement bonus /level |
|------|------|------|---------|---------------------|--------------------------|
| Dairyhand's Bottoms | `/items/dairyhands_bottoms` | legs | milking 90 | milkingEfficiency=0.1; milkingExperience=0.04 | milkingEfficiency=0.002; milkingExperience=0.0008 |
| Forager's Bottoms | `/items/foragers_bottoms` | legs | foraging 90 | foragingEfficiency=0.1; foragingExperience=0.04 | foragingEfficiency=0.002; foragingExperience=0.0008 |
| Lumberjack's Bottoms | `/items/lumberjacks_bottoms` | legs | woodcutting 90 | woodcuttingEfficiency=0.1; woodcuttingExperience=0.04 | woodcuttingEfficiency=0.002; woodcuttingExperience=0.0008 |
| Cheesemaker's Bottoms | `/items/cheesemakers_bottoms` | legs | cheesesmithing 90 | cheesesmithingEfficiency=0.1; cheesesmithingExperience=0.04 | cheesesmithingEfficiency=0.002; cheesesmithingExperience=0.0008 |
| Crafter's Bottoms | `/items/crafters_bottoms` | legs | crafting 90 | craftingEfficiency=0.1; craftingExperience=0.04 | craftingEfficiency=0.002; craftingExperience=0.0008 |
| Tailor's Bottoms | `/items/tailors_bottoms` | legs | tailoring 90 | tailoringEfficiency=0.1; tailoringExperience=0.04 | tailoringEfficiency=0.002; tailoringExperience=0.0008 |
| Chef's Bottoms | `/items/chefs_bottoms` | legs | cooking 90 | cookingEfficiency=0.1; cookingExperience=0.04 | cookingEfficiency=0.002; cookingExperience=0.0008 |
| Brewer's Bottoms | `/items/brewers_bottoms` | legs | brewing 90 | brewingEfficiency=0.1; brewingExperience=0.04 | brewingEfficiency=0.002; brewingExperience=0.0008 |
| Alchemist's Bottoms | `/items/alchemists_bottoms` | legs | alchemy 90 | alchemyEfficiency=0.1; alchemyExperience=0.04 | alchemyEfficiency=0.002; alchemyExperience=0.0008 |
| Enhancer's Bottoms | `/items/enhancers_bottoms` | legs | enhancing 90 | enhancingSpeed=0.1; enhancingExperience=0.04 | enhancingSpeed=0.002; enhancingExperience=0.0008 |

### Feet — "skilling boots"

Collector's Boots: milking/foraging/woodcutting efficiency (gathering-skill boots). No dedicated production-skill boots exist in the data.

| Item | hrid | Slot | Lvl req | Base noncombatStats | Enhancement bonus /level |
|------|------|------|---------|---------------------|--------------------------|
| Collector's Boots | `/items/collectors_boots` | feet | milking 60, foraging 60, woodcutting 60 | milkingEfficiency=0.1; foragingEfficiency=0.1; woodcuttingEfficiency=0.1 | milkingEfficiency=0.002; foragingEfficiency=0.002; woodcuttingEfficiency=0.002 |

### Hands — "skilling gloves"

Enchanted Gloves: enhancingSpeed + alchemyEfficiency. No generic per-skill skilling gloves exist.

| Item | hrid | Slot | Lvl req | Base noncombatStats | Enhancement bonus /level |
|------|------|------|---------|---------------------|--------------------------|
| Enchanted Gloves | `/items/enchanted_gloves` | hands | alchemy 60, enhancing 60 | enhancingSpeed=0.1; alchemyEfficiency=0.1 | enhancingSpeed=0.002; alchemyEfficiency=0.002 |

### Head — chef hat

Red Culinary Hat is the only skilling head item: cooking + brewing efficiency. (No "eyes" equipment slot exists.)

| Item | hrid | Slot | Lvl req | Base noncombatStats | Enhancement bonus /level |
|------|------|------|---------|---------------------|--------------------------|
| Red Culinary Hat | `/items/red_culinary_hat` | head | cooking 60, brewing 60 | cookingEfficiency=0.1; brewingEfficiency=0.1 | cookingEfficiency=0.002; brewingEfficiency=0.002 |

### Off-hand — eye watch

Eye Watch (off_hand slot, not a dedicated "eyes" slot): cheesesmithing/crafting/tailoring efficiency — the handicraft-skill off-hand.

| Item | hrid | Slot | Lvl req | Base noncombatStats | Enhancement bonus /level |
|------|------|------|---------|---------------------|--------------------------|
| Eye Watch | `/items/eye_watch` | off_hand | cheesesmithing 60, crafting 60, tailoring 60 | cheesesmithingEfficiency=0.1; craftingEfficiency=0.1; tailoringEfficiency=0.1 | cheesesmithingEfficiency=0.002; craftingEfficiency=0.002; tailoringEfficiency=0.002 |


## 4. Capes (back slot)

All skilling capes give **Speed 0.05 + Experience 0.03** (0.005 / 0.003 per level) across their skill group. Each has a Refined (★) variant with ~1.16× higher stats. The guild "+3 cape" baseline refers to enhancing a cape to +3 (multiplier 3.3).

### Capes

| Item | hrid | Slot | Lvl req | Base noncombatStats | Enhancement bonus /level |
|------|------|------|---------|---------------------|--------------------------|
| Gatherer Cape | `/items/gatherer_cape` | back | milking 80, foraging 80, woodcutting 80 | milkingSpeed=0.05; foragingSpeed=0.05; woodcuttingSpeed=0.05; milkingExperience=0.03; foragingExperience=0.03; woodcuttingExperience=0.03 | milkingSpeed=0.005000000000000001; foragingSpeed=0.005000000000000001; woodcuttingSpeed=0.005000000000000001; milkingExperience=0.003; foragingExperience=0.003; woodcuttingExperience=0.003 |
| Artificer Cape | `/items/artificer_cape` | back | cheesesmithing 80, crafting 80, tailoring 80 | cheesesmithingSpeed=0.05; craftingSpeed=0.05; tailoringSpeed=0.05; cheesesmithingExperience=0.03; craftingExperience=0.03; tailoringExperience=0.03 | cheesesmithingSpeed=0.005000000000000001; craftingSpeed=0.005000000000000001; tailoringSpeed=0.005000000000000001; cheesesmithingExperience=0.003; craftingExperience=0.003; tailoringExperience=0.003 |
| Culinary Cape | `/items/culinary_cape` | back | cooking 80, brewing 80 | cookingSpeed=0.05; brewingSpeed=0.05; cookingExperience=0.03; brewingExperience=0.03 | cookingSpeed=0.005000000000000001; brewingSpeed=0.005000000000000001; cookingExperience=0.003; brewingExperience=0.003 |
| Chance Cape | `/items/chance_cape` | back | alchemy 80, enhancing 80 | alchemySpeed=0.05; enhancingSpeed=0.05; alchemyExperience=0.03; enhancingExperience=0.03 | alchemySpeed=0.005000000000000001; enhancingSpeed=0.005000000000000001; alchemyExperience=0.003; enhancingExperience=0.003 |
| Gatherer Cape ★ | `/items/gatherer_cape_refined` | back | milking 100, foraging 100, woodcutting 100 | milkingSpeed=0.058; foragingSpeed=0.058; woodcuttingSpeed=0.058; milkingExperience=0.0348; foragingExperience=0.0348; woodcuttingExperience=0.0348 | milkingSpeed=0.0058000000000000005; foragingSpeed=0.0058000000000000005; woodcuttingSpeed=0.0058000000000000005; milkingExperience=0.00348; foragingExperience=0.00348; woodcuttingExperience=0.00348 |
| Artificer Cape ★ | `/items/artificer_cape_refined` | back | cheesesmithing 100, crafting 100, tailoring 100 | cheesesmithingSpeed=0.058; craftingSpeed=0.058; tailoringSpeed=0.058; cheesesmithingExperience=0.0348; craftingExperience=0.0348; tailoringExperience=0.0348 | cheesesmithingSpeed=0.0058000000000000005; craftingSpeed=0.0058000000000000005; tailoringSpeed=0.0058000000000000005; cheesesmithingExperience=0.00348; craftingExperience=0.00348; tailoringExperience=0.00348 |
| Culinary Cape ★ | `/items/culinary_cape_refined` | back | cooking 100, brewing 100 | cookingSpeed=0.058; brewingSpeed=0.058; cookingExperience=0.0348; brewingExperience=0.0348 | cookingSpeed=0.0058000000000000005; brewingSpeed=0.0058000000000000005; cookingExperience=0.00348; brewingExperience=0.00348 |
| Chance Cape ★ | `/items/chance_cape_refined` | back | alchemy 100, enhancing 100 | alchemySpeed=0.058; enhancingSpeed=0.058; alchemyExperience=0.0348; enhancingExperience=0.0348 | alchemySpeed=0.0058000000000000005; enhancingSpeed=0.0058000000000000005; alchemyExperience=0.00348; enhancingExperience=0.00348 |

Skill groupings: **Gatherer** = milking/foraging/woodcutting; **Artificer** = cheesesmithing/crafting/tailoring; **Culinary** = cooking/brewing; **Chance** = alchemy/enhancing.

## 5. Worked examples (effective values)

Using the formula above. Speed/Efficiency/etc. are fractions (0.9 = +90%).

### +7 Holy vs Celestial tool (Foraging shears example — identical pattern for all skills)

**Holy Shears** (`/items/holy_shears`) at **+7** (×9.1):

- `foragingSpeed`: 0.9 + 9.1×0.018000000000000002 = **1.0638**

**Celestial Shears** (`/items/celestial_shears`) at **+7** (×9.1):

- `foragingSpeed`: 1.05 + 9.1×0.021 = **1.2411**
- `foragingRareFind`: 0.15 + 9.1×0.003 = **0.1773**
- `foragingExperience`: 0.04 + 9.1×0.0008 = **0.0473**

So a +7 Holy tool = **+106.38% speed**; a +7 Celestial tool = **+124.11% speed** plus **+17.73% rare find** and **+4.728% experience**. (Enhancing uses success not speed: +7 Holy Enhancer enhancingSuccess = 0.036 + 9.1×0.00072 = **0.042552**; +7 Celestial Enhancer = 0.042 + 9.1×0.00084 = **0.049644**, plus rare find / xp.)

### +7 skilling armour

**Dairyhand's Top** (`/items/dairyhands_top`) at **+7** (×9.1):

- `milkingEfficiency`: 0.1 + 9.1×0.002 = **0.1182**
- `milkingRareFind`: 0.15 + 9.1×0.003 = **0.1773**

**Dairyhand's Bottoms** (`/items/dairyhands_bottoms`) at **+7** (×9.1):

- `milkingEfficiency`: 0.1 + 9.1×0.002 = **0.1182**
- `milkingExperience`: 0.04 + 9.1×0.0008 = **0.0473**

**Collector's Boots** (`/items/collectors_boots`) at **+7** (×9.1):

- `milkingEfficiency`: 0.1 + 9.1×0.002 = **0.1182**
- `foragingEfficiency`: 0.1 + 9.1×0.002 = **0.1182**
- `woodcuttingEfficiency`: 0.1 + 9.1×0.002 = **0.1182**

**Enchanted Gloves** (`/items/enchanted_gloves`) at **+7** (×9.1):

- `enhancingSpeed`: 0.1 + 9.1×0.002 = **0.1182**
- `alchemyEfficiency`: 0.1 + 9.1×0.002 = **0.1182**

**Eye Watch** (`/items/eye_watch`) at **+7** (×9.1):

- `cheesesmithingEfficiency`: 0.1 + 9.1×0.002 = **0.1182**
- `craftingEfficiency`: 0.1 + 9.1×0.002 = **0.1182**
- `tailoringEfficiency`: 0.1 + 9.1×0.002 = **0.1182**

**Red Culinary Hat** (`/items/red_culinary_hat`) at **+7** (×9.1):

- `cookingEfficiency`: 0.1 + 9.1×0.002 = **0.1182**
- `brewingEfficiency`: 0.1 + 9.1×0.002 = **0.1182**

Every +7 skilling armour Efficiency stat (base 0.1) resolves to **0.1182 = +11.82%**; the +7 RareFind (base 0.15) → **0.1773**; the +7 Experience (base 0.04) → **0.04728**.

### +3 cape (guild baseline)

**Gatherer Cape** (`/items/gatherer_cape`) at **+3** (×3.3):

- `milkingSpeed`: 0.05 + 3.3×0.005000000000000001 = **0.0665**
- `foragingSpeed`: 0.05 + 3.3×0.005000000000000001 = **0.0665**
- `woodcuttingSpeed`: 0.05 + 3.3×0.005000000000000001 = **0.0665**
- `milkingExperience`: 0.03 + 3.3×0.003 = **0.0399**
- `foragingExperience`: 0.03 + 3.3×0.003 = **0.0399**
- `woodcuttingExperience`: 0.03 + 3.3×0.003 = **0.0399**

At +3 (×3.3) a base cape gives **+6.65% speed and +3.99% experience** per skill in its group. The Refined variant at +3: speed = 0.058 + 3.3×0.0058 = **0.07714**, experience = 0.0348 + 3.3×0.00348 = **0.046284**.

## 6. Gaps / notes

- **No dedicated "eyes" equipment slot** exists in the data. The "eye watch" is an **off_hand** item; the "chef hat" is the only **head** skilling item. Head/off_hand are the closest matches to the requested eyes/head slots.
- **No per-skill skilling boots or gloves** beyond gathering: only `collectors_boots` (gathering feet) and `enchanted_gloves` (enhancing+alchemy hands). Production/handicraft skills have no dedicated boots/gloves — efficiency for those comes from the off-hand Eye Watch and the tops/bottoms.
- **No item uses a field literally named `<skill>Level`.** Skill-level buffs come from consumables/community buffs, not equipment noncombat stats. Equipment noncombat channels observed: `Speed`, `Efficiency`, `Experience`, `RareFind`, `EssenceFind`, `gatheringQuantity`, `enhancingSuccess`, `skilling*` generics, `taskSpeed`, `drinkConcentration`.
- Enhancing "tools" scale a **success-rate** stat, not a speed stat — treat separately from the other 9 skills when modelling.
- Additional skilling gear not in the requested categories but captured in the JSON: necklaces (speed/efficiency/wisdom + Philosopher's), rings & earrings (gathering/essence/rare + Philosopher's), task badges (taskSpeed, trinket), XP charms (10 skills × 6 tiers), guzzling pouch (drinkConcentration).
