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
TRIAL_PARTY_CAP = 20

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
