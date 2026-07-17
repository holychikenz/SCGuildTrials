"""Static configuration for the guild sheet pipeline.

All values here are derived from the *actual* structure of the published
Google Sheet (verified by fetching the CSV), not from assumptions. If the
sheet layout changes, adjust the column map below and the structure guard in
``reader.py`` will catch the mismatch loudly.
"""

# --- Source spreadsheet -----------------------------------------------------
SHEET_ID = "1b5_zID6K4WRaFXnBMJijSEXr_4l2gi40eFKxuvRJQAE"
GID = "0"

# Anonymous CSV export (verified working: "anyone with link" sharing).
CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    f"{SHEET_ID}/export?format=csv&gid={GID}"
)

# --- Sheet layout -----------------------------------------------------------
# Rows 1-2 are notes / merged-cell group headers -> skipped.
# Row 3 (0-based index 2) is the real header row we validate against.
HEADER_ROW_INDEX = 2  # 0-based index of the real header row
FIRST_DATA_ROW_INDEX = 3  # 0-based index of the first member row

# Ordered skill group names, matching the repeating column blocks left-to-right.
SKILLS = [
    "Milking",
    "Foraging",
    "Woodcutting",
    "C.Smithing",
    "Crafting",
    "Tailoring",
    "Cooking",
    "Brewing",
    "Bell Farming",
    "Enhancing",
]

# Fixed-position columns (0-based).
COL_NAME = 0
COL_MAIN_CLASSES = 1
COL_FLEX = 2

# Five flex-related threshold level columns: 30+, 25+, 35+, 35+, 35+.
FLEX_LEVEL_COLS = [3, 4, 5, 6, 7]
FLEX_THRESHOLDS = ["30+", "25+", "35+", "35+", "35+"]

# Each skill occupies a 4-column block: [level, Tool, Top, Bot].
# The first block (Milking) starts at column 8; blocks are contiguous.
SKILL_BLOCK_START = 8
SKILL_BLOCK_STRIDE = 4
SKILL_LEVEL_OFFSET = 0
SKILL_TOOL_OFFSET = 1
SKILL_TOP_OFFSET = 2
SKILL_BOT_OFFSET = 3

# --- Structure guard --------------------------------------------------------
# Sentinel header cells the parser expects to find (0-based col -> text).
# Values are compared after ``str.strip()``. If any of these fail to match,
# the sheet has been restructured and we must fail loudly rather than emit
# garbage. (Note: the real header cell is "Main Classes " with a trailing
# space; stripping handles that.)
SENTINEL_HEADERS = {
    0: "Member",
    1: "Main Classes",
    2: "Flex",
    9: "Tool",
    10: "Top",
    11: "Bot",
    13: "Tool",  # start of the Foraging block, confirms stride
}

# Network timeout for the CSV fetch, in seconds.
FETCH_TIMEOUT = 30

# --- Named-tab (gviz) fetch -------------------------------------------------
# The gviz endpoint fetches a tab BY NAME rather than gid. It differs from the
# export?format=csv path above in two ways:
#   1. It COLLAPSES the sheet's three header rows into ONE merged, fully-quoted
#      header row (data begins on line 2). Some header cells carry merged junk
#      text prepended and/or trailing spaces.
#   2. It appends trailing "summary" columns after the real member table.
# CRITICAL: gviz does NOT error on an unknown/misspelled sheet name -- it
# silently serves a *different* tab. The gviz header guard in scraper.py is
# therefore mandatory. ``{sheet}`` is filled (url-encoded) at fetch time.
GVIZ_URL = (
    "https://docs.google.com/spreadsheets/d/"
    f"{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={{sheet}}"
)

# Member tabs known to share the SC layout (verified empirically).
TABS = {
    "sc": "SC Member Data",
    "li": "LI Member Data",
}

# Rightmost real column of the member table; rows are sliced to 0..GVIZ_LAST_COL
# inclusive to drop the trailing side-summary junk columns. The layout (name,
# flex, and the 10 four-column skill blocks) is shared with the export path
# above, so Enhancing's Bot cell lands at column 47.
GVIZ_LAST_COL = 47

# gviz wrong-tab / structure guard. Because gviz prepends merged junk text and
# leaves trailing spaces on some header cells, sentinels match by substring
# containment (after str.strip()) unless the mode is "equals". If any fail, the
# tab likely does not exist, gviz served a different tab, or the layout changed.
# 0-based col -> (mode, expected) where mode is "contains" or "equals".
GVIZ_SENTINEL_HEADERS = {
    0: ("contains", "Member"),
    2: ("equals", "Flex"),
    8: ("contains", "Milking"),
    12: ("contains", "Foraging"),
    44: ("contains", "Enhancing"),
}

# ===========================================================================
# Guild Trials (Phase 1) — model constants + this week's draw
# ===========================================================================
# The trials model, tier curve, and all equipment numbers below are documented
# in research/trial-messages.md, research/item-stats.md, and the machine-
# readable research/item-stats.json (game version v1.20260715.0). Numbers are
# transcribed here (rather than parsed from the JSON at runtime) so the model
# has no runtime dependency on the research directory and every constant carries
# an in-line citation. Where a value is a WORKING ASSUMPTION not yet confirmed
# by an empirical capture, it is flagged as such.

# --- Trial skill -> sheet column mapping ------------------------------------
# THE BELL FARMING JOKE: the guild named the sheet's 9th skill column "Bell
# Farming" as an in-joke — the column actually records each member's ALCHEMY
# level (level + Tool/Top/Bot checkboxes). So the trial skill "Alchemy" reads
# the "Bell Farming" sheet column verbatim, exactly like any other skill; there
# is no real "Bell Farming" trial. Every other trial skill maps to its own
# identically-named column (identity). The 10 real trial skills are therefore
# the 9 sheet skills other than "Bell Farming", plus "Alchemy" (= Bell Farming).
TRIAL_SKILL_TO_SHEET_COLUMN = {
    "Alchemy": "Bell Farming",  # the joke: Bell Farming column IS Alchemy
    "Milking": "Milking",
    "Foraging": "Foraging",
    "Woodcutting": "Woodcutting",
    "C.Smithing": "C.Smithing",
    "Crafting": "Crafting",
    "Tailoring": "Tailoring",
    "Cooking": "Cooking",
    "Brewing": "Brewing",
    "Enhancing": "Enhancing",
}

# --- This week's skilling trial draw (Trial Assignments tab, Date 7/17) -----
# research/trial-tabs.md §2.2: Foraging, Woodcutting, Alchemy, Enhancing.
# Change this list for a different weekly draw; everything downstream keys off
# it. Names use the trial's own skill labels; "Alchemy" resolves to the "Bell
# Farming" sheet column via TRIAL_SKILL_TO_SHEET_COLUMN above.
TRIAL_SKILLS_CURRENT = ["Foraging", "Woodcutting", "Alchemy", "Enhancing"]

# --- Random assignment (Phase 1: NO optimizer) ------------------------------
# Fixed seed for reproducibility. NEVER use unseeded randomness.
TRIAL_RNG_SEED = 42
# Skilling trial party cap (research/trial-tabs.md §1: max 20 observed).
# Tunable — parties may run larger than the 20 originally observed. For now this
# is a magic number; a later change will read it from the guild spreadsheet.
TRIAL_PARTY_CAP = 22

# ===========================================================================
# Guild Trials (Phase 2) — optimizer strategy + knobs (src/optimizer.py)
# ===========================================================================
# The optimizer assigns members across the week's 4 skilling trials to maximise
# total guild points, measured against the real simulate_race oracle (the
# objective is non-linear and non-separable — see src/optimizer.py and
# research/trial-messages.md). A "strategy" is constructor[+refiner...]:
#   constructors: random | proxy_greedy | marginal_greedy | beam | genetic
#   refiners:     hill_climb | sa
#
# BAKE-OFF WINNER: chosen by `python -m src.optimize_bakeoff` across multiple
# seeds on live SC data and synthetic rosters (points PRIMARY; the build runs
# once daily in GitHub Actions, so a few minutes of runtime is fine but hours
# are not — budgets below are sized to keep the whole optimize step comfortably
# under ~10 min on the runner). See the "# BAKE-OFF RESULTS" block for the data.
# "best" runs an ensemble of strong pipelines and keeps the max (correctness
# first). Set to "random" to restore Phase-1 behaviour (one-line rollback).
TRIAL_OPTIMIZER_STRATEGY = "best"
# Fixed seed for the optimizer's internal randomness. NEVER use unseeded RNG.
TRIAL_OPTIMIZER_SEED = 1234

# The ensemble run by strategy "best"/"ensemble": diverse strong pipelines whose
# maximum is returned. Beam seeds the genetic algorithm (a strong founder
# converges better); every pipeline ends in hill_climb to lock in a local
# optimum (never worsens the result).
OPT_ENSEMBLE_PIPELINES = [
    "beam+genetic+hill_climb",
    "proxy_greedy+sa+hill_climb",
    "marginal_greedy+sa+hill_climb",
]

# --- BAKE-OFF RESULTS -------------------------------------------------------
# `python -m src.optimize_bakeoff` — synthetic roster n=86, seeds 1-3, at the
# budgets set below (SA 50k iters x2 restarts, GA pop 100 x 200 gens, beam 16).
# Points PRIMARY (higher = better); time is per-run wall-clock on the dev box.
#
#   strategy                        mean_pts  min_pts   time
#   ---------------------------------------------------------
#   genetic (beam-seeded)             5400     5400      20s
#   beam+genetic+hill_climb           5400     5400      21s
#   best (ensemble)                   5400     5400     101s   <-- SHIPPED
#   proxy_greedy                      5300     5300      ~0s
#   scipy_lap (dev-only, Hungarian)   5300     5300      ~0s
#   proxy_greedy+sa+hill_climb        5300     5300      40s
#   marginal_greedy+sa+hill_climb     5133     5100      40s
#   beam                              5000     5000      <1s
#   marginal_greedy                   5000     5000      <1s
#   random                            4667     4600      ~0s
#
# Takeaways:
#  * The beam-seeded GA (your suggestion) reaches the optimum robustly (min ==
#    mean == 5400) — the strongest single method, and cheap (~20s).
#  * scipy_lap (classic linear assignment) only ties the trivial proxy_greedy
#    (5300): it optimises a linear proxy and is blind to the step objective and
#    the headcount penalty — exactly the gap this bake-off set out to measure.
#  * "best" = max over {beam+genetic+hc, proxy_greedy+sa+hc, marginal_greedy+sa+hc}
#    is shipped: it matches the best single method here AND can never do worse
#    than any component on a future roster, at ~100s (well under the ~10-min CI
#    budget). Simulated annealing underperformed the GA here but is retained in
#    the ensemble as cheap diversity insurance.

# --- Local search (hill_climb) ----------------------------------------------
# Best-improvement iteration cap; convergence usually well below this. Bounds
# worst-case build time.
OPT_HILLCLIMB_MAX_ITERS = 500

# --- Simulated annealing (sa) -----------------------------------------------
# Point deltas come in multiples of ~100 (one tier), so the temperature band is
# scaled to that: T_START accepts a one-tier loss ~exp(-0.67); T_END rejects it.
# Restarts spend the daily budget on escaping distinct local optima (best kept).
OPT_SA_ITERS = 50000
OPT_SA_RESTARTS = 2
OPT_SA_T_START = 150.0
OPT_SA_T_END = 0.5

# --- Beam search (beam) -----------------------------------------------------
OPT_BEAM_WIDTH = 16

# --- Genetic algorithm (genetic) --------------------------------------------
OPT_GA_POP = 100
OPT_GA_GENERATIONS = 200
OPT_GA_MUTATION = 0.05
OPT_GA_ELITE = 6
OPT_GA_TOURNAMENT = 3

# --- Tier race budget -------------------------------------------------------
# research/trial-messages.md CORRECTION (2026-07-17): 1 hour PER TRIAL (not per
# tier); the party races cumulatively upward through tiers within this budget.
TRIAL_TIME_BUDGET_SECONDS = 3600

# --- Enhancement multiplier table (item-stats.json
#     enhancementLevelTotalBonusMultiplierTable): +7 -> 9.1x, +3 -> 3.3x -------
ENHANCEMENT_MULT_PLUS7 = 9.1
ENHANCEMENT_MULT_PLUS3 = 3.3

# --- Tool bonuses (for the 9 non-enhancing skills the tool grants SPEED) -----
# Holy tool +7:      base 0.9  + 9.1 * 0.018 = 1.0638   (item-stats.md §5)
# Celestial tool +7: base 1.05 + 9.1 * 0.021 = 1.2411   (item-stats.md §5)
TOOL_SPEED_HOLY_PLUS7 = 1.0638
TOOL_SPEED_CELESTIAL_PLUS7 = 1.2411

# --- Enhancing tool bonus (grants SUCCESS, not speed) -----------------------
# Holy Enhancer +7:      0.036 + 9.1 * 0.00072 = 0.042552   (item-stats.md §5)
# Celestial Enhancer +7: 0.042 + 9.1 * 0.00084 = 0.049644   (item-stats.md §5)
TOOL_SUCCESS_HOLY_PLUS7 = 0.042552
TOOL_SUCCESS_CELESTIAL_PLUS7 = 0.049644

# --- Cape +3 (everyone; assumed correct-group cape) -------------------------
# base 0.05 + 3.3 * 0.005 = 0.0665 speed   (item-stats.md §5 "+3 cape")
# The Chance Cape covers alchemy/enhancing and grants speed for both, so this
# speed bonus applies to every trial skill including Enhancing.
CAPE_SPEED_PLUS3 = 0.0665

# --- +7 skilling armour efficiency (family piece + top + bot) ---------------
# base 0.1 + 9.1 * 0.002 = 0.1182   (item-stats.md §5). This is the value for
# Collector's Boots (milking/foraging/woodcutting), Enchanted Gloves
# (alchemyEfficiency), Eye Watch, Red Culinary Hat, and the skilling top/bottom.
ARMOUR_EFFICIENCY_PLUS7 = 0.1182
# ENHANCING special case: the family "gloves" (Enchanted Gloves) grant
# enhancingSPEED +7 = 0.1182 (item-stats.md §5), NOT efficiency.
GLOVES_ENHANCING_SPEED_PLUS7 = 0.1182

# --- Per-tier work model (research/trial-messages.md WORKING ASSUMPTION) -----
# WORKING ASSUMPTION (2026-07-17): trial tiers mirror the labyrinth model until
# the empirical curve is harvested from captures (see that file's TODO).
TIER_BASE_LEVEL = 100          # tierLevel(1)
TIER_LEVEL_STEP = 10           # +10 per tier
TIER_TARGET_PER_LEVEL = 10     # baseTarget(t) = tierLevel(t) * 10
SUCCESS_BASE = 0.8             # success(m,t) = clamp(0.8 * (1 + levelBonus + successBonus))
LEVEL_BONUS_POS = 0.005        # per-level bonus when member level >= tier level
LEVEL_BONUS_NEG = 0.01         # per-level penalty when member level < tier level
# Headcount penalty: each member raises the required workpower by 1% (linear).
HEADCOUNT_PENALTY_PER_MEMBER = 0.01
ACTION_SECONDS_ENHANCING = 8   # baseActionSeconds for enhancing
ACTION_SECONDS_DEFAULT = 10    # baseActionSeconds for every other skill

# --- Skill families (for the per-category community buffs; MWI categories) ---
# The three live community buffs each target one skill family:
#   gathering  -> gathering-quantity / doubling chance (Milking/Foraging/Woodcutting)
#   production -> production efficiency (C.Smithing/Crafting/Tailoring/Cooking/
#                 Brewing/Alchemy — i.e. everything that is neither gathering nor
#                 enhancing; note the trial skill "Alchemy" is production)
#   enhancing  -> enhancing speed (Enhancing)
GATHERING_SKILLS = frozenset({"Milking", "Foraging", "Woodcutting"})

# --- Community buffs (event) + gear ------------------------------------------
# The gathering buff is modelled as the labyrinth-style `doubleProgressChance`:
# the chance an action counts double, so it scales work rate by (1 + doubleChance)
# exactly as the lab-sim formula does (research/trial-messages.md §"lab-sim model":
# `rate(m,t) = success(m,t) * (1 + doubleChance) * floor(workPower_m) / actionSeconds_m`).
# WORKING ASSUMPTION (2026-07-17): while the community buffs are live, every
# member on a GATHERING skill carries a doubling chance of the +20% community
# gathering buff plus ~+5% naturally on gear (0.25 total); every member on a
# PRODUCTION skill gains +0.15 efficiency from the community production buff;
# every member ENHANCING gains +0.20 speed from the community enhancing buff.
# Placeholders until per-member gear is harvested; the buff terms apply only
# while the respective community buff is active.
COMMUNITY_GATHERING_BUFF_DOUBLE = 0.20   # +20% community gathering buff (event)
GEAR_DOUBLE_CHANCE = 0.05                # ~+5% carried naturally on gear
DOUBLE_CHANCE = COMMUNITY_GATHERING_BUFF_DOUBLE + GEAR_DOUBLE_CHANCE  # 0.25 (gathering only)
COMMUNITY_PRODUCTION_EFFICIENCY_BUFF = 0.15  # +15% efficiency for production skills
COMMUNITY_ENHANCING_SPEED_BUFF = 0.20        # +20% speed for enhancing

# --- Houses (player housing rooms) -------------------------------------------
# Authoritative game data (cowstuff csim houseRoomDetailMap): every skilling
# house room grants an efficiency buff of +0.015/level (Dairy Barn, Garden,
# Log Shed → gathering; Forge, Workshop, Sewing Parlor, Kitchen, Brewery,
# Laboratory → production), EXCEPT the enhancing house (Observatory) which
# grants +0.010 action-SPEED per level (its enhancing-success buff is 0). The
# in-game value is `flatBoost + (level-1)*flatBoostLevelBonus`; for these rooms
# flatBoost == flatBoostLevelBonus, so the value is simply per_level * level.
# ASSUMPTION (2026-07-17): everyone runs a LEVEL-4 house for their trial skill.
HOUSE_LEVEL = 4
_HOUSE_EFFICIENCY_PER_LEVEL = 0.015        # gathering + production house rooms
_HOUSE_ENHANCING_SPEED_PER_LEVEL = 0.010   # Observatory (enhancing house)
HOUSE_EFFICIENCY = _HOUSE_EFFICIENCY_PER_LEVEL * HOUSE_LEVEL           # 0.06 at L4
HOUSE_ENHANCING_SPEED = _HOUSE_ENHANCING_SPEED_PER_LEVEL * HOUSE_LEVEL  # 0.04 at L4

# --- TARGET_SCALE (calibrated) ----------------------------------------------
# The lab-sim tier targets are single-player-scaled, so at TARGET_SCALE=1.0 a
# 20-member party blows through absurdly many tiers. TARGET_SCALE re-scales the
# per-tier target so simulated results land in the guild's observed
# neighbourhood (SC recorded tiers 9-11 for 20-member skilling parties;
# research/trial-tabs.md §1).
#
# CALIBRATION (against live SC Member Data, 86 members, seed 42): swept
# TARGET_SCALE over {10,20,30,40,50,60,80,100} and simulated all four 20-member
# parties for this week's draw. TARGET_SCALE=30 places every party inside the
# observed tier 9-11 band (Foraging 11, Woodcutting 10, Alchemy 10, Enhancing
# 9) — matching SC's recorded results (strong skills at 11, weakest at 9). At 40
# the special Enhancing party falls to tier 8, below the band; at 20 the strong
# gathering parties overshoot to 12. 30 is the cleanest round value that keeps
# the whole draw in-band, so it is adopted.
# TODO: replace with the empirical capture-harvest curve (trial-messages.md).
TARGET_SCALE = 30.0

# Which family/back cape group covers each trial skill is implicit in the model
# (efficiency for gathering/alchemy, speed for enhancing); see trials.py.
