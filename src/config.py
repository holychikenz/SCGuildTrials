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
# Row 2 (0-based index 1) carries the per-skill GROUP name at each block start
# (Milking, Foraging, ... Enhancing). Since the 2026-07-19 header reformat this
# is the strongest structural sentinel available (see SENTINEL_HEADERS note).
SKILL_GROUP_ROW_INDEX = 1  # 0-based index of the skill-group-name row

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

# Fixed-position columns (0-based). SHEET CHANGE (2026-07-24): the leading column
# that briefly sat at index 0 (added 2026-07-17, held only row numbers) was
# DELETED, shifting Member/Main Classes/Flex and the flex thresholds one place
# back LEFT. This also aligns SC with the "LI Member Data" tab, which never had a
# leading column — so ONE column map now serves BOTH guilds (this is what fixed
# the LI-page 404: LI failed the old SC-only map by exactly one column). Each
# skill block still carries an "H" (house level) column between the level and the
# Tool checkbox (stride 5). The maps below reflect the post-2026-07-24 layout.
COL_NAME = 0
COL_MAIN_CLASSES = 1
COL_FLEX = 2

# Five flex-related threshold level columns: 30+, 25+, 35+, 35+, 35+.
FLEX_LEVEL_COLS = [3, 4, 5, 6, 7]
FLEX_THRESHOLDS = ["30+", "25+", "35+", "35+", "35+"]

# Each skill occupies a 5-column block: [level, H (house level), Tool, Top, Bot].
# The first block (Milking) starts at column 8; blocks are contiguous.
SKILL_BLOCK_START = 8
SKILL_BLOCK_STRIDE = 5
SKILL_LEVEL_OFFSET = 0
SKILL_HOUSE_OFFSET = 1
SKILL_TOOL_OFFSET = 2
SKILL_TOP_OFFSET = 3
SKILL_BOT_OFFSET = 4

# --- Structure guard --------------------------------------------------------
# Sentinel header cells on the real header row (HEADER_ROW_INDEX, 0-based col ->
# text). Values are compared after ``str.strip()``. If any fail to match, the
# sheet has been restructured and we fail loudly rather than emit garbage.
# (Note: the real header cell is "Main Classes " with a trailing space;
# stripping handles that.)
#
# SHEET CHANGE (2026-07-19): the guild removed the per-block "H / Tool / Top /
# Bot" sub-label cells from the header row — in the CSV export cols 10-13 (etc.)
# are now blank. The underlying DATA columns are unchanged (stride 5:
# [level, H, Tool, Top, Bot]), so those sub-labels are dropped as sentinels.
# Their structural role is taken over — more strongly — by the skill-group-name
# row (SKILL_GROUP_ROW_INDEX): each block start there must spell the skill name,
# which pins SKILL_BLOCK_START and SKILL_BLOCK_STRIDE for all ten blocks. See
# reader._validate_header.
SENTINEL_HEADERS = {
    0: "Member",
    1: "Main Classes",
    2: "Flex",
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

# gviz HEADER-COLLAPSE OVERRIDE (append to GVIZ_URL).
# gviz does not merely merge a FIXED number of leading rows into its header row —
# it GUESSES how many leading rows are labels, and the guess depends on the
# content above the table. A purely cosmetic edit can therefore swallow real data
# rows into the header, where no parser can see them.
# INCIDENT 2026-07-25: the officers added a 16-row "ALL TRIALS ARE FREE ASSIGNED"
# notice to the top of the "Trial Assignments" tab. gviz absorbed all 17 leading
# rows — the "Skilling Trial Info" banner and the four "Trial N" draw rows with
# them — so draw.parse_draw could no longer find the banner and the whole deploy
# failed (SC is `required`, so every page of every guild stopped shipping).
# Appending "&headers=0" turns the guess OFF: gviz returns every row as data.
#
# CURRENTLY UNUSED, and retained only as the recorded remedy for that failure mode.
# It existed for draw.py's read of the "Trial Assignments" tab, whose banner sat
# below whatever prose the officers wrote above it; since 2026-08-14 the draw is read
# from a sign-up tab's HEADER ROW, which is exactly what gviz's default collapsing
# hands over, so the override would now hide the very row we want. The member-tab and
# sign-up parsers are likewise written against the COLLAPSED form and must NOT be
# given this parameter without rewriting them. Reach for it only if a future parser
# again needs to read rows that sit beneath free-form text.
GVIZ_NO_HEADER_COLLAPSE = "&headers=0"

# Member tabs known to share the SC layout (verified empirically).
TABS = {
    "sc": "SC Member Data",
    "li": "LI Member Data",
}

# The tab whose HEADER ROW publishes this week's skilling-trial draw (src/draw.py).
#
# This is a SIGN-UP tab, and deliberately so: the game writes the sign-up tabs, so
# their four tick-box column headers ARE the draw, whereas the "Trial Assignments"
# tab the draw used to be read from is hand-maintained by the officers — and on
# 2026-08-14 they rebuilt it for the third time, deleting both of the anchors
# draw.py knew. See the src/draw.py docstring for the whole account.
#
# Fixed at Survey Corps' tab rather than read per guild: the draw is shared between
# guilds (identical in every cycle the "Trial Data" log records) and SC's tab is the
# one the game keeps current. On 2026-08-14 the LI tab still held the ENTIRE 8/10
# cycle — its four skills and both its combat bosses — so reading LI's own tab for
# LI's draw would have planned this week from last week's roll. build.build_guild
# cross-checks each guild's own sign-up columns against this draw and withholds that
# guild's plan when they disagree, which reports the staleness instead of absorbing
# it. If the guilds ever genuinely diverge, that cross-check is where it will show.
DRAW_SOURCE_TAB = "SC Trial Signup"

# Rightmost real column of the member table; rows are sliced to 0..GVIZ_LAST_COL
# inclusive to drop the trailing side-summary junk columns. The layout (name,
# flex, and the 10 five-column skill blocks) is shared with the export path
# above, so Enhancing's Bot cell now lands at column 57 (8 + 5*9 + 4).
GVIZ_LAST_COL = 57

# gviz wrong-tab / structure guard. Because gviz prepends merged junk text and
# leaves trailing spaces on some header cells, sentinels match by substring
# containment (after str.strip()) unless the mode is "equals". If any fail, the
# tab likely does not exist, gviz served a different tab, or the layout changed.
# 0-based col -> (mode, expected) where mode is "contains" or "equals".
GVIZ_SENTINEL_HEADERS = {
    0: ("contains", "Member"),
    2: ("equals", "Flex"),
    8: ("contains", "Milking"),
    13: ("contains", "Foraging"),
    53: ("contains", "Enhancing"),
}

# --- Roster tabs (the scripted per-character harvest) ------------------------
# A SECOND, machine-written pair of tabs, produced by the standalone
# `profiles-endpoint` Apps Script from a per-character harvest. One row per
# member, 78 columns, addressed by tab name through the same credential-free
# GVIZ_URL as the member tabs above.
#
# These tabs are NOT the member tabs and share none of their layout: no merged
# header rows, no fixed five-column skill blocks, and a tool-block column order
# that legitimately VARIES upstream (itemLocationDetailMap carries no sortIndex,
# so it comes out alphabetical when client data was captured and in skill order
# from the module's fallback). Everything in src/roster.py therefore addresses
# columns BY HEADER NAME, never by position.
#
# DO NOT append GVIZ_NO_HEADER_COLLAPSE to a roster fetch: these tabs have a
# single clean header row, and "&headers=0" makes gviz blank the label of every
# numeric column — which is most of the tab (verified live 2026-08-31).
ROSTER_TABS = {
    "sc": "SC Roster",
    "li": "LI Roster",
}

# Roster column names per SKILLS entry, and the single source of truth for BOTH
# the parser and the header guard in roster._validate_header — one table, so the
# two can never drift.
#
# Two traps are defused here and nowhere else:
#   - "Bell Farming" is the guild's in-joke name for the ALCHEMY column, so it
#     reads `alchemy` / `house_laboratory` / `tool_alchemy` (the same joke
#     TRIAL_SKILL_TO_SHEET_COLUMN handles for the manual tab);
#   - "C.Smithing" is `cheesesmithing` upstream.
# House-room <-> skill pairing confirmed against the game catalogue.
ROSTER_COLUMNS = {
    #  SKILLS entry     level             house                   tool
    "Milking":      ("milking",        "house_dairy_barn",     "tool_milking"),
    "Foraging":     ("foraging",       "house_garden",         "tool_foraging"),
    "Woodcutting":  ("woodcutting",    "house_log_shed",       "tool_woodcutting"),
    "C.Smithing":   ("cheesesmithing", "house_forge",          "tool_cheesesmithing"),
    "Crafting":     ("crafting",       "house_workshop",       "tool_crafting"),
    "Tailoring":    ("tailoring",      "house_sewing_parlor",  "tool_tailoring"),
    "Cooking":      ("cooking",        "house_kitchen",        "tool_cooking"),
    "Brewing":      ("brewing",        "house_brewery",        "tool_brewing"),
    "Bell Farming": ("alchemy",        "house_laboratory",     "tool_alchemy"),
    "Enhancing":    ("enhancing",      "house_observatory",    "tool_enhancing"),
}
# The tool ENHANCEMENT column is always the tool column plus this suffix
# ("tool_milking" -> "tool_milkingEnh"), so it is derived rather than listed
# again: one place to be wrong instead of two.
ROSTER_TOOL_ENH_SUFFIX = "Enh"

# Per-member columns that are not per-skill. `name` is the join key; capturedAt
# and revision carry staleness; the five shrine columns are each member's OWN
# purchased skilling-shrine level (see the GUILD_SHRINE_LEVELS note far below:
# the guild's level is a CAP, the member's purchase is what reaches the rate).
# All five are read, not just force and tempo, so member_shrine_bonuses can
# dispatch on the same channel table guild_shrine_bonuses uses and a loot or XP
# shrine is refused by the MODEL rather than by never having been parsed.
ROSTER_SINGLETON_COLUMNS = (
    "name",
    "characterId",
    "capturedAt",
    "revision",
    "shrine_force_skilling",
    "shrine_tempo_skilling",
    "shrine_spirit_skilling",
    "shrine_rarity_skilling",
    "shrine_scholar_skilling",
)
# roster shrine column -> GUILD_SHRINE_SKILLING_BUFFS key.
ROSTER_SHRINE_COLUMNS = {
    "shrine_force_skilling": "force",
    "shrine_tempo_skilling": "tempo",
    "shrine_spirit_skilling": "spirit",
    "shrine_rarity_skilling": "rarity",
    "shrine_scholar_skilling": "scholar",
}

# --- Roster tabs as the PRIMARY per-member source: the switch ladder ---------
# MASTER SWITCH. False restores the pre-roster build BIT-FOR-BIT: no second gviz
# fetch, no join, no merge, no new data.json keys, no page changes. The gating is
# at the FETCH rather than at the consumers, deliberately — with this off the
# build does not even talk to the roster tab, so the rollback also covers the case
# where the separate Apps Script deployment is the thing that is broken.
# Pinned by tests/test_roster.py::test_roster_disabled_reproduces_the_golden_week
# and ::test_data_json_is_byte_identical_with_roster_off.
#
# SHIPPED FALSE. R1-R4 land the whole mechanism dark: the merge, the tool table,
# the per-member shrines and the provenance strip all go in first, so that nothing
# ships with better numbers than the page admits to. It flips to True in R5, which
# is the phase that changes published numbers and which reconciles each of the
# four slices against an independently measured band before it does.
ROSTER_SOURCE_ENABLED = True

ROSTER_USE_LEVELS = True             # roster skill levels over the manual tab's
ROSTER_USE_HOUSES = True             # roster house levels over the "H" column /
                                     # DEFAULT_HOUSE_LEVEL
ROSTER_USE_TOOLS = True              # roster tool TIER over the "Tool" checkbox
ROSTER_USE_TOOL_ENHANCEMENT = True   # observed enhancement over the assumed +7.
                                     # False keeps the tier but re-imposes +7 — the
                                     # partial rollback for the -0.52% / -1.26%
                                     # adverse tool slice, which is the only one of
                                     # the four that points against us.
ROSTER_USE_SHRINES = True            # each member's OWN purchased shrine levels in
                                     # place of the guild-wide constant. False
                                     # restores the global GUILD_SHRINE_LEVELS read
                                     # AND simulate_race's once-per-race hoist,
                                     # bit-for-bit.

# Roster-only names are SEATED, not merely reported. Revised 2026-08-31 (plan §5.6):
# the first draft refused them because `yiyaa`/`yiyya` looked like one renamed
# character seated twice. Measured, they are two — distinct characterIds 287196 and
# 287200, different shrines, different tool enhancement, different levels — and a
# duplicate is structurally impossible anyway, because apps-script/profiles/Code.gs
# keys on characterId and UPSERTS, so a rename updates the row in place and two rows
# can only ever mean two characters. The name-collision guard belongs on the MANUAL
# side of the join, where names are the only key; not on the roster side, where they
# are not.
# It matters because both guilds already seat everyone they have (SC 28+24+28+27 =
# 107 = its whole roster; LI 25+24+26+26 = 101 = its whole roster), so these five LI
# members are the only additional capacity in existence — and all five signed up for
# this week's trials, which the R0 build log records itself ignoring.
# False restores "reported, not seated" exactly, and is the one-line rollback.
ROSTER_ADMITS_NEW_MEMBERS = True

# Below this fraction of the MANUAL tab's members joining a roster row, the roster is
# REFUSED for that guild and the build falls back to the manual tab with a loud
# warning. Guards the catastrophic case — gviz serving a different tab past the
# header guard would otherwise silently reprice a whole guild. Measured headroom:
# SC joins at 100%, LI at 99%.
ROSTER_MIN_JOIN_RATE = 0.90

# Age at which the on-page provenance strip is outlined and captioned as stale, in
# the same way the community-buff strip is outlined off the published level. A
# BANNER THRESHOLD, NOT A CUTOFF: an old capture is still better data than the
# assumption it replaces, and refusing it would silently restore the assumption.
ROSTER_MAX_AGE_DAYS = 14

# An item the roster names that config.TOOL_STATS does not model: warn, count, and
# fall back to the manual checkbox. True stops the build instead. Shipped False
# because one new game item must not stop a deploy — but it is never silent, and
# never scored as Holy without saying so.
ROSTER_UNKNOWN_TOOL_FATAL = False

# Enhancement level assumed when the roster names a tool but leaves its Enh cell
# blank. PROVISIONAL, and 0 understates against an observed mode of +5 — chosen
# because the repo's standing habit with an unknown is to err in the direction that
# cannot flatter the answer (see calibrate.DEFAULT's level_common comment). Counted
# and printed every build; if it exceeds 5% of matched member-skills on either guild
# it must be resolved before the R5 flip rather than after.
#
# CLOSED 2026-09-02, and with something better than "no counter-examples". The
# handover's standing complaint was that this constant "is still never exercised on
# live data (zero named-tool-with-blank-enhancement observations on either guild),
# so it remains untested against reality rather than merely provisional". The
# gearSeen union is an INDEPENDENT view of the same fact — the userscript harvests
# every equipped item with its enhancement level, by a different code path from the
# tool columns — and it agrees on 2,020 of 2,020 observations across both guilds:
# same item, same level, no blanks, no mismatches (research/per-item-gear.md §3.4).
#
# So this branch is not merely unobserved, it is CONFIRMED unreachable on today's
# data by two sources that do not share a line of code. It stays, because a future
# upstream change could reintroduce a blank, and because a constant that costs
# nothing to keep should not be removed to make a point.
TOOL_ENHANCE_WHEN_UNKNOWN = 0

# --- Per-item gear from the `gearSeen` union: the switch ladder --------------
# A THIRD per-member source, and the first that reports THINGS OWNED rather than
# numbers. `apps-script/profiles/Code.gs` writes one column at the tail of each
# roster tab -- the UNION of every capture of that member's gear, keyed on hrid,
# keeping the higher enhancement level. src/gear.py turns it into rate terms.
#
# WHAT IT REPLACES. Five constants in this file assert the same equipment of every
# member -- CAPE_SPEED_PLUS3, ARMOUR_EFFICIENCY_PLUS7 three times over (family
# piece, top, bottom) and GEAR_DOUBLE_CHANCE -- and one term is not modelled at
# all: the neck slot, which is the LARGEST single row in RISK_SIGMA_SYSTEMATIC's
# budget at 0.0081-0.0110 of a ~0.0123 total. This is the `stableGear` block the
# roster plan (§11.2) named "the highest-value remaining work in the whole area".
#
# Rules, measurements, and the one judgement call: research/per-item-gear.md.
#
# MASTER SWITCH. False restores the pre-gear build BIT-FOR-BIT: the column is not
# parsed, nothing is resolved, no new data.json keys, no page change. Gated at the
# PARSE rather than at the consumers, exactly as ROSTER_SOURCE_ENABLED is, so the
# rollback also covers the case where the upstream userscript or the Apps Script
# merge is the thing that is broken.
# Pinned by tests/test_gear.py::test_gear_disabled_reproduces_the_golden_week
# and ::test_data_json_is_byte_identical_with_gear_off.
#
# FLIPPED TRUE 2026-09-02 (phase G7), after each of the four slices was reconciled
# against the direction research/per-item-gear.md §7 predicted for it, on BOTH
# guilds independently (§7.1, and research/gear-reconciliation-2026-09-02.txt):
#
#   cape          +1.57 / +1.23 credit   (predicted up)
#   family piece  -0.50 / -1.72          (predicted down)
#   garments      -1.19 / -0.06          (predicted down)
#   accessories  +10.40 / +10.45         (predicted up, and dominant)
#   RE-OPTIMISED +13.64 / +12.06 credit, +14.01 / +12.55 E[points]
#
# STEP POINTS DID NOT MOVE -- 4900 and 4600, before and after, on both guilds --
# and that is the honest headline. The gain is in partial credit, in safety (the
# thinnest trial goes from P = 0.9908 to 1.0000 on SC before the search spends any
# of it back), and above all in what the model can DEFEND: 53% of SC's slot
# resolutions and 51% of LI's are now measured rather than assumed.
#
# The two guilds agreeing to within 0.05 on the accessories (+10.40 against
# +10.45) is the single most reassuring number in the whole change: two rosters of
# different size, level and wealth put almost exactly the same value on reading the
# neck slot, which is what makes the term a property of the game rather than of one
# guild's data.
GEAR_SOURCE_ENABLED = True

# The column name, at the TAIL of the roster tab. NOT added to
# roster.required_columns(): the column is OPTIONAL and must stay so. LI's tab
# lacked it on the morning of 2026-09-02 and gained it by lunchtime; reverting the
# userscript would remove it again, and apps-script/profiles/README.md states that
# a narrower payload leaves the column untouched by design. A missing gearSeen
# must degrade to the constants above, never fail the header guard.
ROSTER_GEAR_COLUMN = "gearSeen"

# Per-slice switches, for a PARTIAL rollback: an adverse slice can be reverted
# without losing the other three. Each False restores that slice's constant.
GEAR_USE_CAPE = True            # per-item cape over CAPE_SPEED_PLUS3
GEAR_USE_FAMILY_PIECE = True    # per-item boots/hat/watch/gloves over the flat +7
GEAR_USE_GARMENTS = True        # per-item top/bottoms over the flat +7
GEAR_USE_ACCESSORIES = True     # neck/ring/earrings. NOTE THE TWO CASES: the NECK
                                # was genuinely unmodelled, so False restores an
                                # OMISSION there (and the sigma row that covered
                                # it), while the ring and earrings were modelled as
                                # the flat GEAR_DOUBLE_CHANCE below, which False
                                # restores as a constant like any other. An earlier
                                # draft conflated the two and the rollback silently
                                # dropped the doubling chance.

# THE ONE LINE THAT REVERSES THIS CHANGE'S LARGEST JUDGEMENT CALL.
# True keeps the universal grant of the four family pieces, correcting only the
# enhancement level from the assumed +7 to each item's observed per-guild mean.
# False scores them only where the union has actually SEEN them.
#
# The measurement says False and the operator chose True, and the disagreement is
# recorded rather than settled (research/per-item-gear.md §3.1): the four pieces
# are held ALL-OR-NOTHING -- 48% of visible members show none of them, 37% show all
# four -- and the obvious objection, that a capture merely caught somebody in
# combat gear, is answered by 82 members who wear a skilling NECKLACE and show not
# one of the four. The grant is kept on the judgement that the union has not yet
# converged and that these pieces are near-universal in practice.
#
# If that judgement is wrong, roughly half of both guilds is credited a 0.1182
# efficiency term it does not own, which would be the single largest mispricing in
# the model. Re-run research/scratch/gear_survey.py §4 in a few weeks: if the
# "0 of four" column has not shrunk, the bimodality is real ownership and this
# switch should move.
GEAR_IMPUTE_FAMILY_PIECE = True

# Whether gatheringQuantity items (the rings and earrings) reach the rate at all.
#
# ISOLATES AN OPEN QUESTION THIS CHANGE DID NOT CREATE. See the note above
# COMMUNITY_GATHERING_BUFF_DOUBLE: the game's `/buff_types/gathering` ("increases
# gathering quantity") is a DIFFERENT buff type from the `doubleProgressChance`
# field this model drives it through. GEAR_DOUBLE_CHANCE was the flat working
# assumption "pending the per-member gear harvest"; the harvest has arrived, and
# per-item modelling makes the question isolable for the first time -- False prices
# every gatheringQuantity item at zero WITHOUT also removing the community buff,
# which the flat constant could not do.
GEAR_GATHERING_IN_RATE = True

# Minimum observations before an imputation statistic is believed. Below this the
# statistic is REFUSED and the shipped constant is used instead.
#
# Refusing is the point. Eight of the eleven observed garment items rest on n=1 or
# n=2, and a mean of one observation is not a mean -- it is worse than the
# assumption it replaces, because it LOOKS measured. The three statistics gear.py
# actually ships are pooled or per-item precisely so that each clears this floor
# with n=24-51 (research/per-item-gear.md §6.1).
GEAR_MIN_IMPUTE_N = 10

# THERE IS DELIBERATELY NO `GEAR_UNKNOWN_ITEM_FATAL`, and the reason is worth
# recording, because ROSTER_UNKNOWN_TOOL_FATAL above is its obvious twin and a
# later reader will wonder why the pair is asymmetric.
#
# The tool check works because the roster's tool columns are NAMED SLOTS: an item
# sitting in `tool_milking` must be a milking tool, so an item TOOL_STATS does not
# know is either a new tier or a shifted header, and both are worth stopping for.
# The gear union has no such structure -- it is a flat list of whatever the member
# had equipped -- and the only catalogue this repo carries,
# research/item-stats.json, holds just the 188 items that HAVE non-combat stats.
# Combat gear is absent from it altogether, so an "is this item known?" test would
# flag every Chaotic Flail and Anchorbound Plate in the union: some sixty items
# per guild, all of them legitimate, none of them actionable.
#
# So gear.GearAudit counts hrids GEAR_STATS does not model and calls them
# UNMODELLED rather than unknown, which is what they are: mostly combat equipment
# with no race-relevant channel. A genuinely new race-relevant item would hide
# among them, and the honest mitigation is a fresh catalogue dump compared against
# GEAR_STATS by tests/test_gear.py -- not a switch that cannot tell the two apart.

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

# --- This week's skilling trial draw (OFFLINE FALLBACK DEFAULT) -------------
# The live build reads the CURRENT draw from DRAW_SOURCE_TAB at build time
# (src/draw.py -> build.main), so this constant is NO LONGER the source of truth —
# the game rerolls the draw each cycle and a hand-edited list here goes stale
# immediately. It remains only as the default for tests and direct library calls
# to trials.run_week / signup.plan that pass no draw.
#
# TREAT THIS CONSTANT AS A HAZARD, not a convenience. On 2026-08-14 the officers'
# rebuild of the "Trial Assignments" tab broke the old parser, build_guild fell back
# to this list behind its "MAY BE STALE" banner, and the site optimised
# [Milking, Foraging, Crafting, Alchemy] for a day while the game had actually rolled
# [Enhancing, Milking, Cooking, Brewing]. The banner is what made that visible; the
# constant is what made it plausible enough to ship. Keeping it current shrinks the
# damage of the next such break but cannot prevent it — the fix is that draw.py now
# reads the tab the GAME writes and no longer chains fallbacks across hand-made
# layouts.
#
# Names use the trial's own skill labels; "Alchemy" resolves to the "Bell Farming"
# sheet column via TRIAL_SKILL_TO_SHEET_COLUMN above.
# Current as of the 8/14 cycle (SC Trial Signup header, columns B–E).
TRIAL_SKILLS_CURRENT = ["Enhancing", "Milking", "Cooking", "Brewing"]

# --- Random assignment (Phase 1: NO optimizer) ------------------------------
# Fixed seed for reproducibility. NEVER use unseeded randomness.
TRIAL_RNG_SEED = 42
# Skilling trial party cap, PER GUILD (research/trial-tabs.md §1: max 20 observed).
# Tunable — parties may run larger than the 20 originally observed. Still magic
# numbers; a later change will read them from the guild spreadsheet.
#
# SPLIT PER GUILD 2026-08-21. It was one constant for both guilds, on the same
# reasoning GUILD_BUILDING_LEVELS still shares one map — until the two diverged.
# Survey Corps runs 28 seats a party, Lactose Intolerance 26. Keyed by the TABS /
# SIGNUP_TABS guild key, so build.GuildSite.party_cap is a one-line lookup.
#
# Under partial credit the cap is priced, not free: an extra head raises every
# tier's work target by 1%, so a cap that is too HIGH seats phantom contributors
# and one that is too LOW leaves points banked (see build._marginal_seat_phrase).
# Being wrong per guild is therefore a real error and no longer a shared one.
TRIAL_PARTY_CAPS = {
    "sc": 28,
    "li": 26,
}

# The cap for callers that name no guild: tests, direct library calls, and the
# bake-off. NOT a third guild — it is the fallback default the ``cap=None``
# arguments of trials.run_week / optimizer.optimize / signup.plan resolve to.
# The live site never reaches it; build.py passes each guild's own cap explicitly.
TRIAL_PARTY_CAP = TRIAL_PARTY_CAPS["li"]


def party_cap(guild: str) -> int:
    """The party cap for one guild key ("sc" | "li").

    Raises KeyError on an unknown key rather than falling back to
    TRIAL_PARTY_CAP: a typo'd guild key silently planning against the wrong
    seat count is exactly the class of quiet wrongness this repo keeps losing
    days to.
    """
    try:
        return TRIAL_PARTY_CAPS[guild]
    except KeyError:
        raise KeyError(
            f"no party cap configured for guild {guild!r}; "
            f"known guilds: {sorted(TRIAL_PARTY_CAPS)}"
        ) from None

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

# The ensemble run by strategy "best"/"ensemble": entries are run independently
# and the maximum is returned. ``optimizer._run_ensemble`` gives entry ``i`` the
# derived seed ``TRIAL_OPTIMIZER_SEED + 1 + i``, so REPEATING a pipeline is not
# redundant — it is a genuine random restart.
#
# REVISED 2026-07-25 after measuring on LIVE rosters (the synthetic bake-off
# roster hid this). The old three-method ensemble
# [beam+genetic+hill_climb, proxy_greedy+sa+hill_climb, marginal_greedy+sa+hill_climb]
# was NOT buying method diversity:
#   * At the SAME seed all three return 4400 on LI (SC: all three 4800).
#   * The ensemble's apparent +100 on LI came entirely from the derived seeds:
#     beam+genetic+hill_climb finds 4500 by itself at seed 1235, while the two SA
#     pipelines spent ~2/3 of the runtime returning 4400s that were discarded.
#   * A seed sweep confirms the variance is in the SEED, not the method: SC scores
#     4800 on all 8 seeds tried; LI scores 4500 on seed 1235 and 4400 on the other
#     seven. The GA also beat both SA pipelines in the synthetic bake-off below.
# So the ensemble was an accidental multi-start. Making that explicit — N restarts
# of the one method that wins everywhere — is cheaper AND more robust, because it
# spends the budget on the axis that actually varies.
# Cost per restart on live data (post-optimisation): ~10.5s SC, ~9.0s LI, against
# 48.9s / 43.0s for the old three-method ensemble.
# Set OPT_RESTARTS = 1 for the cheapest useful run; raising it can only improve
# the result (the maximum is kept), at a linear cost.
OPT_RESTARTS = 4
OPT_ENSEMBLE_PIPELINES = ["beam+genetic+hill_climb"] * OPT_RESTARTS

# --- POST-PATCH RE-BAKE (2026-08-11, partial-tier credit + shrine buffs) ----
# The tables below were measured against the STEP objective. Partial credit changed
# the objective, so the field was re-run; the shipped choice SURVIVES, and the way it
# survived is instructive enough to record.
#
# A quick synthetic run (n=40, one seed) put proxy_greedy+sa+hill_climb a full tier
# ahead of the shipped beam+genetic+hill_climb, which looked like grounds to change
# what ships. It was not. On the LIVE rosters, at the shipped budgets, three seeds
# (1235-1237), draw [Woodcutting, C.Smithing, Crafting, Cooking]:
#
#   strategy                        SC mean_cr   SC step   LI mean_cr   LI step
#   ------------------------------------------------------------------------------
#   beam+genetic+hill_climb  SHIPPED    4971.2      4900      4754.0      4700
#   beam+hill_climb                     4971.1      4900      4754.1      4700
#   proxy_greedy+hill_climb             4970.7      4900      4752.6      4700
#   marginal_greedy+sa+hill_climb       4970.3      4900      4753.3      4700
#   proxy_greedy+sa+hill_climb          4970.2      4900      4754.4      4700
#
# EVERY candidate reaches the SAME deterministic tiers on both guilds; they differ by
# under half a point of credit out of ~4900, which is noise. So the synthetic table
# misled us for the second time in this file's history, and in the same way — see
# "WHY THE SYNTHETIC TABLE ABOVE MISLED US" below, written after the first time.
#
# Worth noting for a future trim: beam+hill_climb matches the shipped pipeline on
# both guilds at 12-14s against 18-21s. Not a reason to churn today, but it is the
# cheaper horse if the optimize step ever needs to come down.
#
# WHAT DID CHANGE, and it is the headline of the whole migration: on LI the
# deterministic total rose 4500 -> 4700 (+200, two whole tiers) at the same seed,
# because the plateaus the search used to grope across became slopes it can walk.
# research/risk-aware-objective.md R1 predicted exactly this ("smoothing the
# objective should make the existing search strictly better"). SC held at 4900.
# The price was a collapsed time margin — see research/partial-tier-credit.md §9.1,
# which is required reading before anyone touches OPT_SLACK_POINTS_TOLERANCE. That
# price has since been PAID OFF by moving the objective to the expectation (§9.1.1,
# OPT_OBJECTIVE below): same banked tiers, thinnest margin 0.01% -> 3.44% (SC) and
# 0.01% -> 6.10% (LI). The +200 recorded here survives the change.
#
# --- BAKE-OFF RESULTS (PRE-PATCH — step objective) --------------------------
# `python -m src.optimize_bakeoff` — synthetic roster n=86, seeds 1-3, at the
# budgets set below (SA 50k iters x2 restarts, GA pop 100 x 200 gens, beam 16).
# Points PRIMARY (higher = better); time is per-run wall-clock on the dev box.
#
#   strategy                        mean_pts  min_pts   time
#   ---------------------------------------------------------
#   genetic (beam-seeded)             5400     5400      20s
#   beam+genetic+hill_climb           5400     5400      21s   <-- now SHIPPED, x4 restarts
#   best (3-method ensemble)          5400     5400     101s   (retired 2026-07-25)
#   proxy_greedy                      5300     5300      ~0s
#   scipy_lap (dev-only, Hungarian)   5300     5300      ~0s
#   proxy_greedy+sa+hill_climb        5300     5300      40s
#   marginal_greedy+sa+hill_climb     5133     5100      40s
#   beam                              5000     5000      <1s
#   marginal_greedy                   5000     5000      <1s
#   random                            4667     4600      ~0s
#
# --- LIVE-DATA RESULTS (2026-07-25, both guilds, post hot-path optimisation) --
# Measured against the real SC (91 members) and LI (78) rosters on draw 7/24
# [Milking, Woodcutting, Crafting, Alchemy]. Points PRIMARY.
#
#   strategy                                 SC pts   LI pts   time (SC/LI)
#   -------------------------------------------------------------------------
#   beam+genetic+hill_climb  @seed 1235       4800     4500     10.5s / 9.0s
#   beam+genetic+hill_climb  @7 other seeds   4800     4400     10.5s / 9.0s
#   proxy_greedy+sa+hill_climb @seed 1234     4800     4400      ~19s / ~17s
#   marginal_greedy+sa+hill_climb @seed 1234  4800     4400      ~19s / ~17s
#   old 3-method ensemble                     4800     4500     48.9s / 43.0s
#   4 restarts of beam+genetic+hill_climb     4800     4500     42.0s / 36.0s  <-- SHIPPED
#
# WHY THE SYNTHETIC TABLE ABOVE MISLED US: on a synthetic roster every method
# landed on the same 5400, which read as "the methods agree, so the ensemble is
# cheap insurance". On live data they also agree — and that is precisely the
# point: the disagreement is between SEEDS, not methods. The old ensemble scored
# its extra tier on LI only because entry 0 drew seed 1235. Spending the same
# budget on restarts of the winning method dominates it.
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
# RESCALED 2026-08-11, and it had to be: the temperature band is meaningless unless
# it matches the size of a typical move delta, and partial-tier credit changed that
# size by two orders of magnitude.
#
# BEFORE: point deltas came in multiples of ~100 (one whole tier, the only thing the
# step objective could see), so T_START = 150 accepted a one-tier loss at
# exp(-100/150) = exp(-0.67) ~ 0.51 and T_END = 0.5 rejected it outright.
#
# AFTER: deltas run ~0.1 to 20 within a tier and ~50 at a tier crossing (the residual
# step, half the old cliff). Keeping T_START = 150 would accept essentially EVERY
# worsening move for the whole run — the schedule would not be annealing at all, it
# would be a random walk. The same design intent, applied to the new scale:
#   * T_START = 15 accepts a 10-point loss (a typical strong relocate, the new
#     analogue of "one tier") at exp(-10/15) = exp(-0.67) — the original figure.
#   * T_END = 0.05 rejects even the smallest meaningful move (~0.1 points, a marginal
#     seat) at exp(-2) = 0.14 and anything larger decisively.
# ``research/risk-aware-objective.md`` R1 anticipated exactly this ("drop it to
# ~0.05").
#
# NB `sa` is not in OPT_ENSEMBLE_PIPELINES, so this does not touch the shipped
# result — but src/optimize_bakeoff.py runs it, and a schedule wrong by 100x would
# make the bake-off's verdict on SA meaningless.
# Restarts spend the daily budget on escaping distinct local optima (best kept).
OPT_SA_ITERS = 50000
OPT_SA_RESTARTS = 2
OPT_SA_T_START = 15.0
OPT_SA_T_END = 0.05

# --- Final safety pass (slack) ----------------------------------------------
# The objective is a STEP function of the tier reached, so it cannot see HOW
# NARROWLY a tier was held. Measured on the live SC roster (2026-07-31): 25
# assignments all scoring exactly 4900 points held their last tier by margins from
# 100 to 560 seconds out of the 3600-second budget — a 2.8% margin on the thinnest,
# which is finer than the error on the model's own constants. Which of those
# assignments shipped was pure luck.
#
# optimizer._refine_slack runs ONE local-search pass after the search has settled,
# maximising (total_points, min_margin, sum_margin) lexicographically. Points come
# first and are compared as exact ints, so the pass CANNOT cost a tier: it only
# chooses which of the equally-scoring optima ships. Slack is read from the same
# simulate_race call the scorer already cached, so it adds no simulations for any
# party the search already visited.
# --- What the optimiser maximises --------------------------------------------
# "expected" -> trials.expected_credit_points, the credit score integrated over the
#               calibrated multiplicative shock. THE SHIPPED DEFAULT since 2026-08-14.
# "credit"   -> trials.simulate_race(...).credit_points, the deterministic score.
#               The one-line rollback, and every strategy's trajectory returns to
#               exactly what it was.
#
# WHY IT CHANGED. research/partial-tier-credit.md §9.1 shipped E[points] as reporting
# only, on a stated prediction: "It does not enter the objective: optimising it would
# pick the same parties, because the gamble it prices survives its own test." THAT
# PREDICTION IS REFUTED. Measured on the 2026-08-14 live SC roster, moving Leevi
# (Enhancing 108 + tool, Brewing 121) out of Brewing for IronThrone (Enhancing 102,
# Brewing 111) costs 0.867 CREDIT points and gains 8.736 EXPECTED ones, taking the
# Enhancing trial from 0.3 seconds of spare time at P(holds) = 0.502 to 31.8 seconds
# at 0.694. The deterministic objective declines that trade by construction, and the
# safety pass cannot rescue it: OPT_SLACK_POINTS_TOLERANCE = 0.0 forbids spending the
# 0.867. So the two objectives do NOT pick the same parties, and the one the README
# already calls "the honest one" was not the one being maximised.
#
# The mechanism, stated plainly, is the ramp. Credit is piecewise linear with a
# 50-point step at every tier boundary, so a party that has just stepped over a
# boundary is worth almost nothing extra per unit of rate, while one mid-ramp is
# worth half a point per 1% of progress. The deterministic score therefore spends
# rate where it pays on paper and leaves the just-crossed tier balanced on a coin.
# E prices that coin, so the search stops buying tiers it cannot hold.
#
# THE COST IS REAL AND IT IS ~3x PER EVALUATION. Measured on the live parties:
# simulate_race 0.145-0.164ms, expected_credit_points a further 0.269-0.318ms (an
# 81-node quadrature plus the Wald sigma), so the oracle goes from ~0.15ms to ~0.45ms
# and the optimiser's ~87k-party pipeline scales with it. §9.2 already took this
# position on a smaller version of the same bill — a cost that buys correctness is
# "worth paying rather than a regression to chase" — and OPT_RESTARTS remains the
# dial. If it ever does matter, the cheap win is that expected_credit_points re-races
# the party for its tau curve when simulate_race has just built most of one.
#
# REQUIRES RISK_EXPECTED_POINTS. With that False, expected_credit_points returns None
# and the scorer falls back to credit per party, which would silently mix two
# currencies inside one search; _objective_value therefore refuses the combination
# loudly rather than shipping a plan scored half one way and half the other.
OPT_OBJECTIVE = "expected"

# Set OPT_SLACK_PASS = False to restore the pre-2026-07-31 behaviour (a one-line
# rollback; nothing else in the pipeline reads the margin).
#
# NOTE its changed standing under OPT_OBJECTIVE = "expected". The pass exists to
# recover margin the deterministic objective could not see; E sees it, and prices it.
# The pass is kept because it is not redundant — E is a sum over trials while risk is
# a MINIMUM over them, so a lineup can maximise E while leaving one trial thin — but
# at OPT_SLACK_POINTS_TOLERANCE = 0.0 it now finds far less to do, which is the
# intended outcome rather than a fault.
OPT_SLACK_PASS = True
# Iteration bound on the pass. Every accepted move strictly increases a bounded
# lexicographic key over a finite state space, so the pass terminates on its own;
# this caps worst-case build time rather than guaranteeing correctness.
OPT_SLACK_MAX_ITERS = 100
# How many guild points the pass may SPEND to widen the thinnest margin.
#
# The pass used to rank on (total_points, min_margin, sum_margin) with the points
# "compared as exact ints, so it cannot trade a tier for margin". Under partial
# credit (TRIAL_PARTIAL_CREDIT_RATE) the points are continuous, exact ties barely
# exist, and that formulation would quietly reduce to a duplicate of the hill-climb.
# The pass is therefore re-founded on an explicit admissibility test — the total may
# fall by at most this much AND the thinnest margin must STRICTLY rise — which turns
# an accident of integer arithmetic into a stated price.
#
# 0.0 keeps the guarantee as strong as a continuous objective allows (no points may
# be lost at all) and makes the pass a no-op when partial credit is off.
OPT_SLACK_POINTS_TOLERANCE = 0.0

# --- Reporting the margin (sign-up page bands) -------------------------------
# The safety pass above only reaches the UNCONSTRAINED optimum. The sign-up plan
# is built under locked volunteer picks (src.signup.plan), so its margin is
# whatever the real sign-ups happen to leave — it can be knife-thin without
# anything in the pipeline noticing. The sign-up page therefore REPORTS the margin
# per trial, banded by these thresholds so a thin lineup is visible at a glance:
#
#   margin <  SLACK_THIN -> red     ("held by seconds; one absence loses the tier")
#   margin <  SLACK_OK   -> amber   (holds, but with less room than the model's own error)
#   margin >= SLACK_OK   -> green   (comfortable)
#
# THIN is set just above the 2.8% knife-edge measured on the live SC roster and the
# 0.26% (9.3s) seen on Lactose lntolerance; OK is set at the ~16-18% the safety
# pass actually achieves on both rosters, so "green" means "as safe as the
# optimizer knows how to be". Display only — nothing optimises against these.
SLACK_THIN = 0.05
SLACK_OK = 0.15

# --- Turning the margin into a PROBABILITY (src.trials.clear_probability) ----
# A margin is an ordinal comfort; officers plan against odds. Under a
# multiplicative shock on the party rate (R~ = R*exp(eps)) the clearing time is
# tau*exp(-eps), so
#
#     P(tier holds) = Phi( ln(BUDGET / tau_T) / sigma ) = Phi( -ln(1 - m) / sigma )
#
# The margin enters as the LOG of the slowdown the party can absorb, because the
# shock is multiplicative. Two pieces make up sigma, added in quadrature:
#
#  1. ALEATORIC — the per-action dice, derived exactly per party and per tier by
#     trials.clear_sigma (Wald first passage). It is NOT a constant: it runs
#     ~0.014-0.019 across the live lineups and rises with the tier as success
#     rates fall toward SUCCESS_FLOOR.
#  2. SYSTEMATIC — everything else, and the constant below.
#
# RISK_SIGMA_SYSTEMATIC comes from the calibration campaign (src/calibrate.py).
# It covers unmodelled neck/ring/earring gear (no source this repo reads has a
# column for those slots), enhancement levels away from the assumed +7, mis-ticked
# tool checkboxes, and house-level slips.
#
# RECALIBRATED 2026-09-01 (plan phase R6), 0.0131 -> 0.0123, after the scripted
# roster tab became the primary per-member source. Three of the four things the
# constant covers are now OBSERVED per member — the tool's actual item, its actual
# enhancement level, and the house level read off the game's own building map — so
# pricing them as unknown had become a pessimism that was knowingly false, and
# `expected_credit_points` (the shipped objective) under-reached because of it.
# calibrate.Sources.respect_provenance skips exactly those draws for a member+skill
# whose provenance tag says "roster", and only those: the 9 SC / 7 LI members who
# hide their gear keep every one of them.
#
#   NOW      sigma_total 0.0221, aleatoric 0.0183, remainder
#            sqrt(0.0221^2 - 0.0183^2) = 0.0123
#            SC Milking, tier 12, seed 20260901, 20 000 reps. The LARGEST of the
#            eight live trials (SC + LI x four drawn skills); the other seven run
#            0.0085-0.0117, so one constant serving both guilds over-covers all but
#            this row, which is the direction this constant is meant to err in.
#            Reproduced at seeds 20260801 (0.0120) and 777 (0.0121); the spread over
#            three seeds is +/-0.0002, and the max is quoted rather than the mean.
#   CONTROL  0.0141 on the SAME row and seed with --ignore-provenance, i.e. the
#            same post-merge lineup with the observed quantities priced as unknown
#            anyway. That 0.0141 -> 0.0123 is the recalibration proper.
#   BEFORE   0.0131, from the pre-roster campaign (live SC lineup 2026-08-01):
#            sigma_total 0.0231 against an aleatoric 0.0190, i.e.
#            sqrt(0.0231^2 - 0.0190^2) = 0.0131, at that lineup's marginal tier.
#
# IT SHRANK BUT DID NOT VANISH, and the second half of that matters more than the
# first. The full ablation is published in research/roster-as-primary-source.md §3;
# its largest single row is the unrecorded NECK slot's efficiency (0.0081-0.0110
# across the eight trials), which this change does not touch at all and cannot
# until the upstream `stableGear` block is harvested (plan §11.2). Retiring the
# three observed sources removes ~0.0023 in quadrature from a ~0.012 budget, which
# is a real cut and a small one. A sigma near zero here would have been a BUG, not
# a triumph: it would mean provenance was being respected for uncertainties that
# remain genuinely unknown, and every published P(holds) would be over-confident on
# exactly the thin trials the risk bridge exists to flag.
#
# DELIBERATELY EXCLUDED, and each for a stated reason:
#   * turnout       — this tool says WHERE to go and WHEN to switch, not IF a
#                     member shows up. The published number is conditional on the
#                     assigned party turning up.
#   * sheet staleness — one-sided (levels only rise), so excluding it can only
#                     make the answer conservative.
#   * model form    — the work formulas are confirmed, not guessed. Where a
#                     constant IS a placeholder (GEAR_DOUBLE_CHANCE, the
#                     COMMUNITY_* buffs) it moves the answer by a whole TIER, not
#                     by a few points of probability, so it belongs in a scenario
#                     rather than smeared into sigma.
#
# VALIDATED against an independent action-level simulation (src/simulate_trial.py,
# 20 000 runs rolling every die): predicted 0.8309 vs realised 0.8407 on the
# thinnest live lineup, with the entire 1-point residual accounted for by the
# simulator's own O(dt) grid bias. Coverage across a deadline sweep: mean absolute
# error 0.014. The published number over-covers by design.
#
# RECALIBRATED 2026-09-02 (phase G8), 0.0123 -> 0.0098, after the gearSeen union
# became a per-item rate model. The neck / ring / earring slots were this
# constant's LARGEST single row and the thing it was most obviously wrong about:
# "no source this repo reads has a column for those slots" is no longer true, and
# 178 of 202 members now have their necklace read off their own card.
#
#   NOW      0.0098. The largest of the EIGHT live trials (SC + LI x four drawn
#            skills) -- SC Milking, tier 12, 20 000 reps -- reproduced at three
#            seeds: 0.0094 (20260902), 0.0098 (20260801), 0.0094 (777). Spread
#            +/-0.0002, and the MAX is quoted rather than the mean, as R6 did.
#            The other seven trials run 0.0034-0.0057, so one constant serving
#            both guilds over-covers all but this row -- which is the direction
#            this constant is meant to err in.
#   CONTROL  0.0135 on the SAME lineup and seed with --ignore-provenance, i.e.
#            every observed quantity priced as unknown anyway. That 0.0135 ->
#            0.0098 is the recalibration proper. Note it sits ABOVE the 0.0123
#            this replaces, exactly as R6's 0.0141 sat above the 0.0131 IT
#            replaced, and for the same reason: the control un-retires the
#            ROSTER's tool and house observations too, which 0.0123 had already
#            banked.
#   BEFORE   0.0123, from the roster campaign (R6, 2026-09-01).
#
# THE CONTROL VALIDATES ITSELF, which is the part worth trusting. Its neck-
# efficiency ablation row comes back at 0.0083 / 0.0103 / 0.0111 / 0.0087 across
# the four SC trials, against 0.0084 / 0.0101 / 0.0111 / 0.0089 measured on the
# PRE-GEAR model, on a different lineup and at a tenth of the replicates. Two
# independent routes to the same four numbers is what makes the 0.0135 a "before"
# rather than an artefact. With provenance respected that row falls to 0.0025 /
# 0.0079 / 0.0031 / 0.0044 -- a real cut, and a PARTIAL one by design.
#
# IT SHRANK BY A FIFTH AND NOT BY THE WHOLE NECK ROW, and the reasons are all
# stated rather than hoped for:
#   * 24 of 202 members show no necklace at all and 16 hide their gear entirely.
#     research/per-item-gear.md §6.2 declines to impute an accessory onto anybody
#     -- the Philosopher's pieces are the rarest items in the game -- so those
#     members keep the old uncertainty in FULL.
#   * The cape and the four family pieces are IMPUTED at this guild's own mean,
#     which is a NEW uncertainty no earlier sigma carried, priced by resampling
#     from the guild's observed spread (Sources.gear_impute_resample).
#   * Milking carries the largest remainder on BOTH guilds because it is the one
#     gathering trial in this week's draw, so it alone still pays for the ring and
#     earrings of the members who wear neither.
# A sigma near zero here would have been a BUG, not a triumph, for exactly the
# reason R6 gave: it would mean provenance was being respected for uncertainties
# that remain genuinely unknown, and every published P(holds) would be
# over-confident on the thin trials the risk bridge exists to flag.
#
# The GOLDEN TEST reports 0.00e+00 on all eight trials: with every source off, the
# perturbed mirror reproduces simulate_race EXACTLY with the gear path live. That
# is the hook design vindicated -- had calibrate.py carried a MIRROR of
# gear.resolve instead of a hook into it, that zero would be a small non-zero
# number and every sigma above would be quietly wrong.
#
# Full campaign output: research/gear-sigma-campaign-2026-09-02.txt.
#
# Set to 0.0 to publish the aleatoric floor alone (a one-line change).
RISK_SIGMA_SYSTEMATIC = 0.0098

# --- E[points]: the number officers should actually plan against --------------
# WHY THIS BECAME NECESSARY on 2026-08-11, having been deferred for weeks as
# "Model 2" in research/risk-aware-objective.md §4. Partial-tier credit made the
# objective continuous, which let the optimizer find genuinely better assignments
# (+200 deterministic points on Lactose Intolerance). It found them by reaching for
# tiers it holds by SECONDS: measured live, three of eight trials bank their credited
# tier with 1-4 seconds to spare, at P(holds) ~ 0.51. See
# research/partial-tier-credit.md §9.1 for why that is the right gamble and not a
# regression — falling short lands on the tier below with ~99% partial credit, so the
# downside is shallow and reaching wins on expectation by ~28 points.
#
# But it makes the DETERMINISTIC score an optimistic point estimate: the page was
# publishing 1200.03 for a lineup worth ~1173 in expectation. E[points] is the honest
# figure, and partial credit is exactly what makes it computable — under the step
# objective an expectation needed the whole tier distribution, whereas now points is a
# smooth monotone function of the realised clearing times.
#
# THE MODEL. Same multiplicative shock as the probability bridge: the party's rate is
# R*exp(eps) with eps ~ N(0, sigma^2) and sigma from the same two terms (the party's
# own Wald dice via trials.clear_sigma, plus RISK_SIGMA_SYSTEMATIC in quadrature). A
# rate shock is exactly a clock shock, so every cumulative clearing time scales by
# exp(-eps) and the tier reached and partial progress follow deterministically. The
# expectation is then one integral over eps.
#
# It changes NOTHING about which lineup is chosen — this is reporting, not the
# objective — for the reason above: the gamble survives an expectation test, so
# optimising E[points] would pick the same parties. Set False to stop computing and
# publishing it (a one-line rollback; the pages fall back to the deterministic figure).
RISK_EXPECTED_POINTS = True
# How many tiers PAST the deterministic outcome to price. A favourable shock can carry
# a party further than the nominal race did, and truncating at the deterministic tier
# would silently discard that upside — research/risk-aware-objective.md Phase 0 asked
# for exactly this ("carry RISK_LOOKAHEAD_TIERS so the race records one or two tiers
# past the failure for the upside terms"). 3 covers a +3-sigma shock at the measured
# sigmas of 0.02-0.03 with room to spare.
RISK_LOOKAHEAD_TIERS = 3
# Quadrature nodes across [-RISK_QUADRATURE_SPAN, +span] sigmas. A plain normalised
# midpoint grid rather than Gauss-Hermite, deliberately: the build must stay
# pure-Python (numpy is a dev-only extra, see pyproject) and a hard-coded Hermite node
# table is exactly the kind of thing one mistypes. The integrand is bounded and the
# cost is four races per guild — well outside the optimizer's hot loop — so accuracy
# here is free and correctness is worth more than elegance. 81 nodes over +/-5 sigma
# reproduces the deterministic answer to <1e-9 as sigma -> 0 (asserted in the tests).
RISK_QUADRATURE_NODES = 81
RISK_QUADRATURE_SPAN = 5.0

# --- Safety swaps on the sign-up page ---------------------------------------
# The advisory, POINTS-PRESERVING counterpart to the sign-up page's existing points
# swaps (signup._safety_swaps). It admits a move only when the total points are
# EXACTLY unchanged and the thinnest margin STRICTLY rises — note both, because
# optimizer._refine_slack's points-first ranking is weaker on each count: it permits a
# points GAIN (which belongs to the points swaps, and which a live probe found paired
# with a margin collapse to 0.23%) and it permits a move that improves only the margin
# SUM, leaving the thin trial exactly where it was.
#
# The pass stops as soon as the thinnest banking trial clears SIGNUP_SAFETY_TARGET
# — it exists to get a lineup off the buzzer, not to gold-plate a healthy one, and
# stopping there keeps the advisory list short enough that officers read it.
SIGNUP_SAFETY_TARGET = SLACK_OK
# Hard bound on the number of recommended moves. A list nobody will carry out is
# worse than a short one; anything needing more than this is a sign-up problem,
# not a fill problem, and the page says so.
SIGNUP_SAFETY_MAX_MOVES = 8
# Whether the pass may fall back to moving a VOLUNTEER once the uncommitted members
# alone cannot lift the thinnest trial. It is the SC case that makes this necessary:
# the thin trial's party was entirely volunteers, so phase 1 had nothing to work with
# and without this the page could only shrug. Every such move is flagged on the page.
# Set False for a guild that would rather never see a sign-up questioned.
SIGNUP_SAFETY_ALLOW_OVERRIDES = True
# How many guild points a safety swap may COST. The counterpart of
# OPT_SLACK_POINTS_TOLERANCE, and for the same reason.
#
# THIS CONSTANT EXISTS TO PREVENT A SILENT REGRESSION. The pass admitted a move only
# when `key[0] == base_points` — an EXACT equality, which was sound while points were
# integers and two lineups could genuinely tie. Under partial credit that equality
# matches essentially nothing, so the list would come out EMPTY and the page would
# print "None found" with no test failing (the existing safety-swap tests would pass
# vacuously). The tolerance restores the pass's reach and states its price.
#
# 0.0 preserves the page's original promise — the score does not change — because a
# move must then leave the total no lower than it found it. Raise it only with the
# page copy changed to match: the footnote currently guarantees "same points".
SIGNUP_SAFETY_POINTS_TOLERANCE = 0.0

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
# The enhancement level the pre-roster model ASSUMED on every gear piece. Named
# rather than written as a bare 7, because ROSTER_USE_TOOL_ENHANCEMENT = False
# re-imposes it as the partial rollback of the tool slice, and a reader needs to
# see that the 7 there is this assumption rather than a coincidence. Observed
# reality is a mode of +5 and a spread from 0 to +14 (research/roster-as-primary-
# source.md), which is why the assumption is worth naming before replacing.
ENHANCEMENT_ASSUMED_LEVEL = 7

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

# --- The full tool catalogue, transcribed from research/item-stats.json ---
# item name -> (SKILLS entry, model channel, base, per enhancement level).
# effectiveStat = base + ENHANCEMENT_MULT_TABLE[level] * per, which is exactly
# calibrate._stat's rule, generalised from four constants to eighty items.
#
# TRANSCRIBED, not read at runtime: config.py's header states the rule — the
# model has no runtime dependency on the research directory. Regenerated and
# compared by tests/test_trials.py::test_tool_table_matches_item_stats_json,
# the same discipline calibrate._load_multiplier_table's two asserts already
# apply to the multiplier curve.
#
# ONLY THE RACE-RELEVANT STAT IS CARRIED. Celestial tools also grant
# <skill>RareFind and <skill>Experience; those buff loot and XP and must not
# enter a RATE model, for exactly the reason guild_shrine_bonuses refuses
# Rarity, Spirit and Scholar. Pinned by
# test_tool_table_carries_no_loot_or_xp_stats.
#
# Values are rounded to 12 decimal places, which recovers the catalogue's
# intended decimals from upstream float noise (0.018000000000000002 -> 0.018,
# 0.0007199999999999999 -> 0.00072). That rounding is what makes the four
# shipped *_PLUS7 constants reproduce EXACTLY at +7 rather than one ULP away,
# and _prepare_member's docstring explains why one ULP matters here.
TOOL_STATS = {
    "Azure Alembic":      ('Bell Farming' , 'speed'   , 0.3, 0.006),
    "Azure Brush":        ('Milking'      , 'speed'   , 0.3, 0.006),
    "Azure Chisel":       ('Crafting'     , 'speed'   , 0.3, 0.006),
    "Azure Enhancer":     ('Enhancing'    , 'success' , 0.012, 0.00024),
    "Azure Hammer":       ('C.Smithing'   , 'speed'   , 0.3, 0.006),
    "Azure Hatchet":      ('Woodcutting'  , 'speed'   , 0.3, 0.006),
    "Azure Needle":       ('Tailoring'    , 'speed'   , 0.3, 0.006),
    "Azure Pot":          ('Brewing'      , 'speed'   , 0.3, 0.006),
    "Azure Shears":       ('Foraging'     , 'speed'   , 0.3, 0.006),
    "Azure Spatula":      ('Cooking'      , 'speed'   , 0.3, 0.006),
    "Burble Alembic":     ('Bell Farming' , 'speed'   , 0.45, 0.009),
    "Burble Brush":       ('Milking'      , 'speed'   , 0.45, 0.009),
    "Burble Chisel":      ('Crafting'     , 'speed'   , 0.45, 0.009),
    "Burble Enhancer":    ('Enhancing'    , 'success' , 0.018, 0.00036),
    "Burble Hammer":      ('C.Smithing'   , 'speed'   , 0.45, 0.009),
    "Burble Hatchet":     ('Woodcutting'  , 'speed'   , 0.45, 0.009),
    "Burble Needle":      ('Tailoring'    , 'speed'   , 0.45, 0.009),
    "Burble Pot":         ('Brewing'      , 'speed'   , 0.45, 0.009),
    "Burble Shears":      ('Foraging'     , 'speed'   , 0.45, 0.009),
    "Burble Spatula":     ('Cooking'      , 'speed'   , 0.45, 0.009),
    "Celestial Alembic":  ('Bell Farming' , 'speed'   , 1.05, 0.021),
    "Celestial Brush":    ('Milking'      , 'speed'   , 1.05, 0.021),
    "Celestial Chisel":   ('Crafting'     , 'speed'   , 1.05, 0.021),
    "Celestial Enhancer": ('Enhancing'    , 'success' , 0.042, 0.00084),
    "Celestial Hammer":   ('C.Smithing'   , 'speed'   , 1.05, 0.021),
    "Celestial Hatchet":  ('Woodcutting'  , 'speed'   , 1.05, 0.021),
    "Celestial Needle":   ('Tailoring'    , 'speed'   , 1.05, 0.021),
    "Celestial Pot":      ('Brewing'      , 'speed'   , 1.05, 0.021),
    "Celestial Shears":   ('Foraging'     , 'speed'   , 1.05, 0.021),
    "Celestial Spatula":  ('Cooking'      , 'speed'   , 1.05, 0.021),
    "Cheese Alembic":     ('Bell Farming' , 'speed'   , 0.15, 0.003),
    "Cheese Brush":       ('Milking'      , 'speed'   , 0.15, 0.003),
    "Cheese Chisel":      ('Crafting'     , 'speed'   , 0.15, 0.003),
    "Cheese Enhancer":    ('Enhancing'    , 'success' , 0.006, 0.00012),
    "Cheese Hammer":      ('C.Smithing'   , 'speed'   , 0.15, 0.003),
    "Cheese Hatchet":     ('Woodcutting'  , 'speed'   , 0.15, 0.003),
    "Cheese Needle":      ('Tailoring'    , 'speed'   , 0.15, 0.003),
    "Cheese Pot":         ('Brewing'      , 'speed'   , 0.15, 0.003),
    "Cheese Shears":      ('Foraging'     , 'speed'   , 0.15, 0.003),
    "Cheese Spatula":     ('Cooking'      , 'speed'   , 0.15, 0.003),
    "Crimson Alembic":    ('Bell Farming' , 'speed'   , 0.6, 0.012),
    "Crimson Brush":      ('Milking'      , 'speed'   , 0.6, 0.012),
    "Crimson Chisel":     ('Crafting'     , 'speed'   , 0.6, 0.012),
    "Crimson Enhancer":   ('Enhancing'    , 'success' , 0.024, 0.00048),
    "Crimson Hammer":     ('C.Smithing'   , 'speed'   , 0.6, 0.012),
    "Crimson Hatchet":    ('Woodcutting'  , 'speed'   , 0.6, 0.012),
    "Crimson Needle":     ('Tailoring'    , 'speed'   , 0.6, 0.012),
    "Crimson Pot":        ('Brewing'      , 'speed'   , 0.6, 0.012),
    "Crimson Shears":     ('Foraging'     , 'speed'   , 0.6, 0.012),
    "Crimson Spatula":    ('Cooking'      , 'speed'   , 0.6, 0.012),
    "Holy Alembic":       ('Bell Farming' , 'speed'   , 0.9, 0.018),
    "Holy Brush":         ('Milking'      , 'speed'   , 0.9, 0.018),
    "Holy Chisel":        ('Crafting'     , 'speed'   , 0.9, 0.018),
    "Holy Enhancer":      ('Enhancing'    , 'success' , 0.036, 0.00072),
    "Holy Hammer":        ('C.Smithing'   , 'speed'   , 0.9, 0.018),
    "Holy Hatchet":       ('Woodcutting'  , 'speed'   , 0.9, 0.018),
    "Holy Needle":        ('Tailoring'    , 'speed'   , 0.9, 0.018),
    "Holy Pot":           ('Brewing'      , 'speed'   , 0.9, 0.018),
    "Holy Shears":        ('Foraging'     , 'speed'   , 0.9, 0.018),
    "Holy Spatula":       ('Cooking'      , 'speed'   , 0.9, 0.018),
    "Rainbow Alembic":    ('Bell Farming' , 'speed'   , 0.75, 0.015),
    "Rainbow Brush":      ('Milking'      , 'speed'   , 0.75, 0.015),
    "Rainbow Chisel":     ('Crafting'     , 'speed'   , 0.75, 0.015),
    "Rainbow Enhancer":   ('Enhancing'    , 'success' , 0.03, 0.0006),
    "Rainbow Hammer":     ('C.Smithing'   , 'speed'   , 0.75, 0.015),
    "Rainbow Hatchet":    ('Woodcutting'  , 'speed'   , 0.75, 0.015),
    "Rainbow Needle":     ('Tailoring'    , 'speed'   , 0.75, 0.015),
    "Rainbow Pot":        ('Brewing'      , 'speed'   , 0.75, 0.015),
    "Rainbow Shears":     ('Foraging'     , 'speed'   , 0.75, 0.015),
    "Rainbow Spatula":    ('Cooking'      , 'speed'   , 0.75, 0.015),
    "Verdant Alembic":    ('Bell Farming' , 'speed'   , 0.225, 0.0045),
    "Verdant Brush":      ('Milking'      , 'speed'   , 0.225, 0.0045),
    "Verdant Chisel":     ('Crafting'     , 'speed'   , 0.225, 0.0045),
    "Verdant Enhancer":   ('Enhancing'    , 'success' , 0.009, 0.00018),
    "Verdant Hammer":     ('C.Smithing'   , 'speed'   , 0.225, 0.0045),
    "Verdant Hatchet":    ('Woodcutting'  , 'speed'   , 0.225, 0.0045),
    "Verdant Needle":     ('Tailoring'    , 'speed'   , 0.225, 0.0045),
    "Verdant Pot":        ('Brewing'      , 'speed'   , 0.225, 0.0045),
    "Verdant Shears":     ('Foraging'     , 'speed'   , 0.225, 0.0045),
    "Verdant Spatula":    ('Cooking'      , 'speed'   , 0.225, 0.0045),
}

# The game's enhancementLevelTotalBonusMultiplierTable, VERBATIM (21 entries,
# +0 .. +20). Not rounded: calibrate._load_multiplier_table reads the same
# array straight from the JSON and asserts equality with this list, so any
# normalisation here would put the model and the calibration campaign on two
# different curves. Note ENHANCEMENT_MULT_PLUS7 / _PLUS3 above are entries 7
# and 3 of this list, and remain as the named constants the shipped model uses.
ENHANCEMENT_MULT_TABLE = [
    0, 1, 2.1, 3.3, 4.6,
    6, 7.5, 9.1, 10.8, 12.600000000000001,
    14.500000000000002, 16.7, 19.2, 22, 25.1,
    28.5, 32.2, 36.2, 40.50000000000001, 45.1,
    50,
]

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

# --- Per-tier work model (CONFIRMED formulas, per Orvel 2026-07-17) ----------
# TotalWork(t, N) = DifficultyLevel(t) * 400 * (1 + N/100), where the difficulty
# level IS the tier level (100, 110, ... — see GUILD-TRIALS.md: the engine's
# tier fields hold the level). SuccessRate uses the effective level
# (SkillLevel + BuildingSkillLevels) vs the difficulty level, floored at 0.05:
#   delta = SkillLevel + BuildingSkillLevels - DifficultyLevel
#   rate  = MAX(0.05, 0.8 * (1 + delta*0.005 + successBonus))  if delta >= 0
#   rate  = MAX(0.05, 0.8 * (1 + delta*0.01  + successBonus))  if delta <  0
# For Enhancing, successBonus carries the EnhancingSuccessRate = enhancer tool
# success (EnhancerBonus) + Observatory enhancing-success (0 in live data) +
# achievement bonus (unmodelled → 0); see trials.member_bonuses.
TIER_BASE_LEVEL = 100          # tierLevel(1) == DifficultyLevel(1)
TIER_LEVEL_STEP = 10           # +10 per tier
TIER_TARGET_PER_LEVEL = 400    # TotalWork(t) = DifficultyLevel(t) * 400
SUCCESS_BASE = 0.8             # base success rate
SUCCESS_FLOOR = 0.05           # MAX(0.05, ...): success never drops below 5%
LEVEL_BONUS_POS = 0.005        # per-level bonus when effective level >= difficulty
LEVEL_BONUS_NEG = 0.01         # per-level penalty when effective level <  difficulty
# Guild points awarded for a completed trial: points(T) = 100 + 100*T for the
# tier T reached (trials.points_for_tier; ASSUMPTION, matching the only observed
# messages — milking tier1 -> 200, tier2 -> 300, research/trial-messages.md).
# The STEP is what a building upgrade buys: one extra tier is worth
# TRIAL_POINTS_PER_TIER guild points EVERY time that trial is run, which is what
# makes an upgrade's payback computable (see TRIAL_WEEKS_BETWEEN_DRAWS).
TRIAL_POINTS_BASE = 100        # points(T) intercept: awarded for finishing at all
TRIAL_POINTS_PER_TIER = 100    # points(T) slope: what one extra tier is worth
# BuildingSkillLevels: skill levels contributed by buildings, added to the
# member's own level in the success calc. TWO DISTINCT SYSTEMS feed this, and an
# earlier revision of this comment conflated them:
#   * per-member HOUSE ROOMS (houseRoomDetailMap) grant EFFICIENCY / action-speed,
#     never skill levels — see the "Houses" section below; and
#   * guild-wide GUILD BUILDINGS (guildBuildingDetailMap) DO grant skill levels,
#     +2 per building level to every member — see GUILD_BUILDING_LEVELS below.
# The per-skill guild-building term is resolved by
# trials.guild_building_skill_levels(); there is no flat scalar any more.
# Headcount penalty: each participant raises the work target by 1% (the (1+N/100)
# term in TotalWork).
HEADCOUNT_PENALTY_PER_MEMBER = 0.01
ACTION_SECONDS_ENHANCING = 8   # baseActionSeconds for enhancing
ACTION_SECONDS_DEFAULT = 10    # baseActionSeconds for every other skill

# ===========================================================================
# Partial-tier credit (game patch 2026-08-11)
# ===========================================================================
# Patch note, verbatim: "Partial-tier progress is tracked when a trial ends,
# granting partial rewards. 0.5% credit per 1% progress. up to 50% credit at
# 99.99% but incomplete."
#
# That is a pure LINEAR rule of slope 0.5 with no separate cap — 0.5 * 99.99% =
# 49.995%, so the quoted "up to 50%" is the limit of the rule, not a clamp on it:
#
#     creditTiers = tier_reached + TRIAL_PARTIAL_CREDIT_RATE * progress_fraction
#
# where progress_fraction is how far into the first UNCLEARED tier the party got
# when the hour ran out (trials.tier_progress_fraction).
#
# WHY THIS IS THE MOST CONSEQUENTIAL CONSTANT IN THE FILE. Before the patch,
# points were a STEP function of the integer tier, so a member who crossed no
# threshold was worth EXACTLY zero and could be seated for free — the entire
# justification for optimizer._fill_bench ("no harm done") and for the
# points-preserving safety passes, which relied on exact integer ties existing at
# all. Partial credit makes the objective a RAMP of height 50 followed by a STEP of
# 50 at each tier boundary: the old 100-point cliff is HALVED, not removed (which is
# why signup._compound_reshuffle_into still has work to do), and every seat now
# moves the score in one direction or the other. Measured on a live-shaped party,
# the sign changes between a member contributing 1.1% and 1.0% of party throughput
# — see research/partial-tier-credit.md for that table and the derivation.
#
# RESOLVED 2026-08-11: the credit lands on GUILD POINTS (there is no separate loot
# table for guild trials), so this is the objective and not merely a display figure.
#
# SET TO 0.0 to restore the pre-patch step function EXACTLY — credit_points becomes
# float(points) bit for bit, and every optimizer trajectory is identical. That is the
# one-line rollback for the whole objective change.
TRIAL_PARTIAL_CREDIT_RATE = 0.5

# Whether the flat TRIAL_POINTS_BASE is awarded on PARTIAL progress alone, i.e.
# before any tier has been completed at all.
#
# UNCONFIRMED, and deliberately set to the conservative reading. The shipped
# schedule points(T) = 100 + 100*T is anchored on exactly two observations
# (tier1 -> 200, tier2 -> 300) with points(0) == 0, so the 100 reads as a bonus for
# COMPLETING a tier rather than for making progress toward one. False therefore
# awards partial credit alone (no base) while tier_reached == 0, and adds the base
# only once a tier is actually banked — understating an unconfirmed gain, as the
# model does everywhere else. Set True if a capture ever shows a party that cleared
# nothing being credited the base.
#
# Note this edge case cannot arise on a real lineup: every live party reaches tier
# 10-12. It exists so that tiny and empty parties are scored coherently.
TRIAL_PARTIAL_CREDIT_BASE_ON_PARTIAL = False

# --- Float-noise guard for a now-CONTINUOUS objective ------------------------
# With integer points, "strictly improving" was exact. With partial credit the move
# deltas are floats, and trials._prepare_member documents why an ULP matters here: a
# one-ULP change in a party rate once left SC on the same 4800 points while
# reshuffling every party for no gain. Every strict comparison in the search
# therefore admits a move only if it beats the incumbent by more than this.
#
# NOT a correctness requirement. Termination never depended on integrality — every
# accepted move strictly increases a bounded key over a finite state space, which
# cannot cycle in float any more than in int — so this buys DETERMINISM.
OPT_POINTS_EPS = 1e-9

# --- How many guild points will we pay to include one more member? -----------
# Under the old step objective a marginal member was worth exactly zero, so seating
# them cost nothing and optimizer._fill_bench could call it "no harm done". Partial
# credit prices them: a member earns their seat iff they contribute more than roughly
# 1/(100 + N) of the party's throughput at the contested tier (0.81% at N=24).
# Inclusion is therefore a PURCHASE, and it gets a price rather than a silent
# default — the sign-up page prints the bill.
#
# 0.0 = seat nobody who costs points. Raise it to buy stragglers a seat in the
# reward at a stated cost. Measured on the live 2026-08-11 rosters this changes
# nothing either way: every seated member already clears the break-even and the
# bench is produced by TRIAL_PARTY_CAP, not by marginal value.
TRIAL_FILL_MAX_POINT_COST = 0.0

# --- Skill families (for the per-category community buffs; MWI categories) ---
# The three live community buffs each target one skill family:
#   gathering  -> gathering-quantity / doubling chance (Milking/Foraging/Woodcutting)
#   production -> production efficiency (C.Smithing/Crafting/Tailoring/Cooking/
#                 Brewing/Alchemy — i.e. everything that is neither gathering nor
#                 enhancing; note the trial skill "Alchemy" is production)
#   enhancing  -> enhancing speed (Enhancing)
GATHERING_SKILLS = frozenset({"Milking", "Foraging", "Woodcutting"})

# --- Community buffs (event) + gear ------------------------------------------
# The MAGNITUDES here are CONFIRMED game data, read from the client dump's
# `communityBuffTypeDetailMap` (`/Users/morgan/pie/farm/cowstuff/milkyway_client_info.json`,
# gameVersion v1.20260715.0) and written up in research/community-buffs.md. Each
# community buff is bought with cowbells and carries its OWN level ladder 1..20;
# the magnitude follows the same in-game rule the buildings and shrines use,
#
#     value(level) = flatBoost + (level - 1) * flatBoostLevelBonus
#
# but — UNLIKE the buildings, houses and shrines — here `flatBoost` does NOT equal
# `flatBoostLevelBonus`, so the `per_level * level` shortcut those three rely on
# MUST NOT be extended to these. A community buff opens at a large base and then
# creeps. Verbatim from the dump:
#
#   gathering_quantity    -> /buff_types/gathering      flat 0.20 + 0.005/level
#   enhancing_speed       -> /buff_types/action_speed    flat 0.20 + 0.005/level
#   production_efficiency -> /buff_types/efficiency      flat 0.14 + 0.003/level
#
# The other two entries in the map are deliberately UNMODELLED, for exactly the
# reason research/guild-shrines.md §2 gives for Rarity/Spirit/Scholar: `experience`
# grants /buff_types/wisdom (XP, which the race never reads) and
# `combat_drop_quantity` is combat loot. Neither is in the trial race's loop.
#
# OPEN QUESTION (research/community-buffs.md §3): the gathering buff's type is
# `/buff_types/gathering` — "Increases gathering quantity" — while the engine field
# this model drives it through, `doubleProgressChance`, belongs to the SEPARATE type
# `/buff_types/labyrinth_double_progress`. Modelling gathering quantity as double
# progress therefore remains a WORKING ASSUMPTION, and the one that would cost the
# most if wrong: DOUBLE_CHANCE would fall to the 0.05 gear placeholder, taking ~16%
# off every gathering party's rate. The settling measurement is a
# `guild_skilling_updated` capture from a GATHERING trial while the buff is live.
COMMUNITY_BUFF_MAX_LEVEL = 20   # every community buff's ladder caps at level 20

# (flatBoost, flatBoostLevelBonus) per modelled skill family, straight from the
# dump. Read by trials.community_buff_value(); the three constants below are this
# ladder evaluated at COMMUNITY_BUFF_LEVEL, and a test pins that they agree.
COMMUNITY_BUFF_LADDER = {
    "gathering": (0.20, 0.005),
    "production": (0.14, 0.003),
    "enhancing": (0.20, 0.005),
}

# The level the site PUBLISHES by default, and the level the OPTIMISER runs at. 1 is
# the honest default: it is the level a buff sits at the moment anyone funds it at
# all, and the guild's real levels are not in any capture this repo holds (the same
# gap GUILD_SHRINE_LEVELS carries). The trials page additionally carries the whole
# 1..20 ladder behind a selector — see TRIALS_BUFF_LEVEL_SLIDER.
COMMUNITY_BUFF_LEVEL = 1

# The community-buff level selector on the trials page: ONE optimiser run at
# COMMUNITY_BUFF_LEVEL, then that same plan re-rated at every rung of the ladder and
# shipped inline, so the reader can move the level without the page fetching or
# recomputing anything (trials.run_week_ladder).
#
# WHAT IT ANSWERS, AND WHAT IT DOES NOT. Moving the selector answers "what would THIS
# WEEK'S PLAN score if the buffs were at level N". It does NOT answer "what is the
# best plan at level N" — the optimiser would seat different members, and would score
# at least as much. Every rung is therefore a LOWER BOUND, which is the same
# fixed-party bound probe_building_upgrade and probe_shrine_upgrade already publish
# and must be labelled the same way on the page.
#
# The bound is also the more OPERATIONAL of the two questions: the parties are settled
# early in the week and nobody redrafts them, while cowbells can be spent at any hour.
# If a buff is funded mid-week, the re-rated figure is what actually happens.
#
# Cost: ~2ms per rung against 56-95s for an optimiser run, so the entire ladder is
# free beside the one search that produced it. False is the one-line rollback —
# no selector, no inline ladder, trials.html exactly as it was.
TRIALS_BUFF_LEVEL_SLIDER = True

# The level-20 COUNTERFACTUAL page (trials-maxbuffs.html/.json): a SECOND, complete
# optimiser run under trials.community_buff_level(COMMUNITY_BUFF_MAX_LEVEL), with the
# parties it seats redrawn rather than merely re-rated.
#
# OFF since 2026-08-14, superseded by TRIALS_BUFF_LEVEL_SLIDER. The selector covers
# all twenty rungs where this covered one, keeps the roster still while the reader
# moves the level (this page reshuffled every party, so "which trial am I in" changed
# under the reader's hand), and costs milliseconds where this cost a whole second
# search — measured at SC 90.8s / LI 95.1s, DEARER than the published run, because at
# level-20 buffs the parties reach higher tiers and every simulate_race in the hot
# loop runs longer.
#
# What was lost with it is real and is the one thing the selector cannot give: the
# TRUE optimum at a raised level, i.e. the size of the reallocation the selector's
# lower bound leaves on the table. The whole path is intact — _unit_jobs still queues
# the unit, _compute_unit still runs it, _render_buff_toggle still renders the switch,
# and the tests still exercise all three — so True restores it, and the two controls
# coexist by design.
TRIALS_PUBLISH_MAXBUFF_PAGE = False

# The register (index.html + data.json) CARRIES this week's assignments: a compact
# `week` block (parties as name lists, the bench, the draw and whether it may be
# stale) and a `trial` stamp on every member. A projection of trials.json, not a copy
# — no rates, tools or timelines — so that one fetch of data.json answers both "what
# does each member have" and "what is each member doing this week"; the in-game
# script that asked for this has one request to spend. trials.json is unchanged and
# stays the full record. See build._attach_week.
#
# False is the one-line rollback: no `week` key, no `trial` keys, no Trial column —
# data.json's key set exactly as before, pinned by
# tests/test_register_week.py::test_flag_off_is_byte_identical_and_on_is_additive.
REGISTER_CARRIES_WEEK = True

# --- Build concurrency (src/build.py) ---------------------------------------
# The build's four optimiser units — two guilds x {published regime, maxed-buff
# counterfactual} — are mutually independent and are run in parallel PROCESSES. See
# the long note above build._GuildInputs for the whole argument; the two constraints
# worth repeating here are that the output is bit-identical (every seed is fixed and
# no unit reads another's state) and that threads would NOT do, because
# trials.community_buff_level rebinds module globals on this very module.
#
# BUILD_PARALLEL = False is the one-line rollback: the same units, run serially in one
# process. Reach for it when a traceback needs reading without a pool in the way, or
# to confirm by hand that serial and parallel agree.
BUILD_PARALLEL = True

# Cap on worker processes. None -> os.cpu_count(). The pool is sized to
# min(units, this), so it never spawns more children than there is work; a public-repo
# GitHub runner has 4 vCPUs, which is exactly the four units.
BUILD_MAX_WORKERS = None

# The three live magnitudes, = COMMUNITY_BUFF_LADDER at COMMUNITY_BUFF_LEVEL.
# The gathering buff is applied as the labyrinth-style `doubleProgressChance`: the
# chance an action counts double, scaling work rate by (1 + doubleChance) exactly
# as the lab-sim formula does (research/trial-messages.md §"lab-sim model":
# `rate(m,t) = success(m,t) * (1 + doubleChance) * floor(workPower_m) / actionSeconds_m`)
# — see the OPEN QUESTION above. Each term applies only while its buff is active;
# scenario_buffs_lapsed in src/calibrate.py prices the lapse as a regime.
COMMUNITY_GATHERING_BUFF_DOUBLE = 0.20 + (COMMUNITY_BUFF_LEVEL - 1) * 0.005
COMMUNITY_PRODUCTION_EFFICIENCY_BUFF = 0.14 + (COMMUNITY_BUFF_LEVEL - 1) * 0.003
COMMUNITY_ENHANCING_SPEED_BUFF = 0.20 + (COMMUNITY_BUFF_LEVEL - 1) * 0.005

# WORKING ASSUMPTION, and the one term here that is NOT from the dump: ~+5%
# doubling chance carried naturally on gear, pending the per-member gear harvest.
GEAR_DOUBLE_CHANCE = 0.05
DOUBLE_CHANCE = COMMUNITY_GATHERING_BUFF_DOUBLE + GEAR_DOUBLE_CHANCE  # 0.25 (gathering only)

# --- Houses (player housing rooms) -------------------------------------------
# Authoritative game data (cowstuff csim houseRoomDetailMap): every skilling
# house room grants an efficiency buff of +0.015/level (Dairy Barn, Garden,
# Log Shed → gathering; Forge, Workshop, Sewing Parlor, Kitchen, Brewery,
# Laboratory → production), EXCEPT the enhancing house (Observatory) which
# grants +0.010 action-SPEED per level (its enhancing-success buff is 0). The
# in-game value is `flatBoost + (level-1)*flatBoostLevelBonus`; for these rooms
# flatBoost == flatBoostLevelBonus, so the value is simply per_level * level.
# The guild sheet now records each member's per-skill house level in the new "H"
# column, so trials.member_bonuses reads the REAL level (clamped to 0..8). When
# the H cell is blank we fall back to DEFAULT_HOUSE_LEVEL (the former flat
# assumption of 4).
DEFAULT_HOUSE_LEVEL = 4   # assumed when a member's per-skill "H" cell is blank
HOUSE_MAX_LEVEL = 8       # in-game house rooms cap at level 8
HOUSE_EFFICIENCY_PER_LEVEL = 0.015        # gathering + production house rooms
HOUSE_ENHANCING_SPEED_PER_LEVEL = 0.010   # Observatory (enhancing house)
# Default (blank-cell) contributions, retained for reference/tests.
HOUSE_EFFICIENCY = HOUSE_EFFICIENCY_PER_LEVEL * DEFAULT_HOUSE_LEVEL           # 0.06 at L4
HOUSE_ENHANCING_SPEED = HOUSE_ENHANCING_SPEED_PER_LEVEL * DEFAULT_HOUSE_LEVEL  # 0.04 at L4

# --- Guild buildings (guild-wide SKILL-LEVEL buffs) --------------------------
# NOT the same thing as the per-member house rooms above, and the difference is
# the whole point: a house room buffs its owner's efficiency, whereas a GUILD
# building raises the SKILL LEVEL of every guild member in that skill.
#
# Authoritative game data (cowstuff milkyway_client_info.json ->
# guildBuildingDetailMap, game version v1.20260715.0): each of the ten skilling
# guild buildings carries exactly one buff of type "/buff_types/<skill>_level"
# with flatBoost == flatBoostLevelBonus == 2, so by the in-game rule
# `flatBoost + (level-1)*flatBoostLevelBonus` the granted levels are simply
#     skillLevels = GUILD_BUILDING_SKILL_LEVELS_PER_LEVEL * buildingLevel
# i.e. +2 levels per building level, to a maximum of +40 at building level 20.
# Verbatim example:
#     {"hrid": "/guild_buildings/brewery", "name": "Guild Brewery",
#      "maxLevel": 20, "skillHrid": "/skills/brewing",
#      "buffs": [{"typeHrid": "/buff_types/brewing_level",
#                 "flatBoost": 2, "flatBoostLevelBonus": 2, "ratioBoost": 0}]}
# Building -> trial skill (all ten follow the identical +2/level pattern). This
# list is TRANSCRIBED into BUILDING_HRID_TO_SKILL below, which is what the sheet
# reader dispatches on; keep the two in step (a test pins the dict against
# GUILD_BUILDING_LEVELS' own keys, so a typo there cannot go quiet):
#   dairy_barn -> Milking        forge      -> C.Smithing   kitchen    -> Cooking
#   garden     -> Foraging       workshop   -> Crafting     brewery    -> Brewing
#   log_shed   -> Woodcutting    sewing_parlor -> Tailoring laboratory -> Alchemy
#   observatory -> Enhancing  (the GUILD Observatory grants enhancing LEVELS —
#                              distinct from the personal Observatory's speed)
#
# WHERE IT APPLIES: the success calc only. Orvel's confirmed formula names
# BuildingSkillLevels in the success delta (`delta = SkillLevel +
# BuildingSkillLevels - DifficultyLevel`) and nothing yet confirms whether the
# level buff also raises workPower, so trials.work_power still uses the raw
# sheet level. If a capture later shows progressPerAction rising with a guild
# building, work_power must take the effective level too — see trials.work_power.
GUILD_BUILDING_SKILL_LEVELS_PER_LEVEL = 2   # +2 skill levels per building level
GUILD_BUILDING_MAX_LEVEL = 20               # in-game guild buildings cap at 20
# Live building levels, keyed by TRIAL skill name (the model's own labels, so
# "Alchemy" is the Guild Laboratory — the "Bell Farming" joke does not reach
# here). A skill omitted, None, or 0 grants nothing. Values are clamped to
# 0..GUILD_BUILDING_MAX_LEVEL by trials.guild_building_skill_levels.
#
# THIS MAP IS THE FALLBACK, NOT THE LIVE DATA — since 2026-09-09. Each guild's
# real levels are read from its own Buildings tab (BUILDING_TABS below, parsed by
# src/buildings.py) and bound around that guild's optimiser unit by
# trials.guild_building_levels_scope. This map is what runs when
# BUILDINGS_SOURCE_ENABLED is off, when a guild's tab cannot be read, or when the
# tab exists but has never been written (which is LI's case today).
#
# It stays ALL ZERO on purpose, and the zeros are load-bearing in two ways:
#   1. tests/test_roster.py::test_roster_disabled_reproduces_the_golden_week calls
#      trials.run_week bare — entering no scope — and compares with `==` against a
#      golden generated at commit 265326b. Zeros are what keep it bit-identical.
#   2. They are the pre-2026-07-25 behaviour (identical to the retired
#      BUILDING_SKILL_LEVELS = 0), so BUILDINGS_SOURCE_ENABLED = False is a true
#      one-line rollback rather than a rollback to some other guess.
# A blank tab therefore reads as "no building modelled" rather than as an
# observation of zero — which is the honest answer for a guild we cannot see, and
# the same direction of error the repo takes everywhere else.
#
# The 2026-07-22 guild_updated capture this map used to hold (SC: builders_hall 3,
# guild_hall 4, skilling_encampment 1, combat_encampment 1, dojo 1, plus the
# force/tempo shrines — none granting a skill level) is superseded by the tab and
# kept only in this sentence. The instruction that used to stand here — "SPLIT THIS
# PER GUILD the moment real levels arrive ... thread its key through
# trials.run_week -> simulate_race/optimize -> rate" — was discharged by reading the
# tab instead, and by binding rather than threading. See
# .claude/plans/buildings-tab-implementation-plan.md §3 for why threading was
# rejected: ten call sites read this global at CALL time, so a scope reaches all of
# them for free, exactly as trials.community_buff_level already argues.
GUILD_BUILDING_LEVELS = {
    "Milking": 0,       # /guild_buildings/dairy_barn
    "Foraging": 0,      # /guild_buildings/garden
    "Woodcutting": 0,   # /guild_buildings/log_shed
    "C.Smithing": 0,    # /guild_buildings/forge
    "Crafting": 0,      # /guild_buildings/workshop
    "Tailoring": 0,     # /guild_buildings/sewing_parlor
    "Cooking": 0,       # /guild_buildings/kitchen
    "Brewing": 0,       # /guild_buildings/brewery
    "Alchemy": 0,       # /guild_buildings/laboratory
    "Enhancing": 0,     # /guild_buildings/observatory
}

# In-game display names, for the upgrade table on the trials page.
GUILD_BUILDING_NAMES = {
    "Milking": "Guild Dairy Barn",
    "Foraging": "Guild Garden",
    "Woodcutting": "Guild Log Shed",
    "C.Smithing": "Guild Forge",
    "Crafting": "Guild Workshop",
    "Tailoring": "Guild Sewing Parlor",
    "Cooking": "Guild Kitchen",
    "Brewing": "Guild Brewery",
    "Alchemy": "Guild Laboratory",
    "Enhancing": "Guild Observatory",
}

# Guild-point cost to REACH each building level (guildBuildingDetailMap
# guildPointCosts, verbatim). The cost of a +1 upgrade from level L is therefore
# GUILD_BUILDING_POINT_COSTS[L+1]; a level-0 (unbuilt) building costs 500 to
# raise to level 1. Cumulative cost to reach L is the running sum, which is why
# the model quotes the marginal step rather than a total.
# ALL TEN skilling buildings share this one curve (as do the seven combat
# buildings and the two encampments — verified: 19 buildings, one identical
# cost map). The four utility buildings (Guild Hall, Archives, Builder's Hall,
# Treasury) sit on a curve of exactly DOUBLE these numbers, and are not modelled
# here because they grant no skill levels.
GUILD_BUILDING_POINT_COSTS = {
    1: 500,      2: 675,      3: 900,      4: 1225,     5: 1650,
    6: 2250,     7: 3025,     8: 4075,     9: 5525,    10: 7450,
    11: 10050,  12: 13575,   13: 18325,   14: 24725,   15: 33400,
    16: 45075,  17: 60850,   18: 82150,   19: 110900,  20: 149725,
}

# --- Guild buildings: the LIVE source (per-guild "Buildings" tab) ------------
# NEW 2026-09-09. The in-game Tampermonkey module reads guildBuildingLevelMap off
# guild_updated / init_character_data and POSTs it, via the Apps Script endpoint in
# apps-script/, to a per-guild tab of the same public sheet everything else here is
# read from. One row per building and per shrine, 28 rows, header
#   Building | Hrid | Kind | Level | Guild Id | Captured At
# parsed by src/buildings.py through the same credential-free GVIZ_URL as the member
# and roster tabs. See apps-script/README.md for the writer's side of the contract.
#
# THE TABS ARE CREATED BY HAND AND START EMPTY ("the first write fills them"), so an
# EMPTY tab is a normal state and not an error: buildings.parse_buildings returns
# observed=False for it and the guild runs on GUILD_BUILDING_LEVELS. As of
# 2026-09-09 that is exactly LI's position — SC's tab holds 28 rows, LI's is 0 bytes.
BUILDINGS_SOURCE_ENABLED = True
# False -> the build never fetches a Buildings tab and every guild runs on
# GUILD_BUILDING_LEVELS, bit-for-bit as before 2026-09-09. The one-line rollback,
# and the same shape of master switch as ROSTER_SOURCE_ENABLED / SHRINE_BUFFS_APPLY_IN_TRIALS.

BUILDING_TABS = {
    "sc": "SC Buildings",
    "li": "LI Buildings",
}

# Each guild's in-game id, for the cross-check in buildings.parse_buildings: every
# row of a Buildings tab carries the id of the guild it was captured from, so a tab
# holding the OTHER guild's levels is caught rather than modelled. That failure is
# silent, plausible (the module routes by a hand-edited guild-id -> tab map) and
# precisely the class config.shrine_caps' docstring refuses to fall back on.
# Source: apps-script/Code.gs:79.
GUILD_IDS = {
    "sc": 4,
    "li": 240,
}

# gviz wrong-tab / structure guard for a Buildings tab, in the same spirit as
# GVIZ_SENTINEL_HEADERS but by "equals" throughout: this tab is machine-written with
# one clean header row, so there is no merged junk to tolerate and any deviation is
# real. gviz does NOT error on an unknown tab name — it silently serves a DIFFERENT
# tab (measured 2026-09-09: a bogus name returned 3518 bytes of the first tab), which
# is what makes this guard mandatory rather than defensive.
# DO NOT append GVIZ_NO_HEADER_COLLAPSE to a Buildings fetch: see that constant's
# note — "&headers=0" blanks the label of every numeric column.
BUILDINGS_SENTINEL_HEADERS = {
    0: ("equals", "Building"),
    1: ("equals", "Hrid"),
    2: ("equals", "Kind"),
    3: ("equals", "Level"),
    4: ("equals", "Guild Id"),
    5: ("equals", "Captured At"),
}

# --- Combat teams: the optimiser's ONE write to the sheet (per-guild machine tab) ----
# NEW 2026-09-09. The combat-trial optimiser in ~/pie/SCLIRoster publishes its
# recommended teams — one row per seated member — through the same Apps Script
# endpoint in apps-script/ that the sign-up and buildings blocks use, to a per-guild
# tab of the public sheet. Header (seven REQUIRED columns guarded by equals below,
# plus three OPTIONAL appended ones — see COMBAT_OPTIONAL_HEADERS):
#   Member | Trial Hrid | Team | Role | Slot | Guild Id | Generated At
#                                      [| Loadout Id | Loadout [| Loadout Name]]
# Parsed by src/combat.py and attached to trials.json as a top-level `combat` key, for
# the in-game userscript that glows a member's assigned tiles. NON-REQUIRED: any failure
# degrades to `available: false` with the reason, and never stops the deploy — SC is
# `required`, and the 2026-07-25 incident above is what a required parse failure costs.
#
# THE TABS ARE MACHINE-OWNED AND START EMPTY. An empty tab is a normal state (the
# optimiser has not published yet); a hand-edited one fails the header guard loudly.
# DO NOT append GVIZ_NO_HEADER_COLLAPSE: one clean header row, exactly what gviz's
# default collapse hands over (see that constant's note, and buildings.py's).
#
# False is the one-line rollback: no fetch, no `combat` key — trials.json byte-identical,
# pinned by tests/test_combat.py::test_flag_off_is_byte_identical_and_on_is_additive.
COMBAT_SOURCE_ENABLED = True

COMBAT_TABS = {
    "sc": "SC Combat Teams",
    "li": "LI Combat Teams",
}

# gviz wrong-tab / structure guard for a Combat Teams tab, equals throughout (machine-
# written, no merged junk). gviz serves the FIRST tab for an unknown name (measured
# 2026-09-09), so this is mandatory, not defensive. Must match SCLIRoster
# optimizer/src/publish/combatTab.js HEADER and apps-script/Code.gs's 'combat' format.
COMBAT_SENTINEL_HEADERS = {
    0: ("equals", "Member"),
    1: ("equals", "Trial Hrid"),
    2: ("equals", "Team"),
    3: ("equals", "Role"),
    4: ("equals", "Slot"),
    5: ("equals", "Guild Id"),
    6: ("equals", "Generated At"),
}

# The two cells the optimiser APPENDED on 2026-09-15, carrying its recommended
# LOADOUT for each seated member. Kept in a PARALLEL map rather than added to the
# required one above, and that is the whole backwards-compatibility lever: the
# required map stays exactly seven entries, so a tab written by the OLD writer —
# seven columns, no loadout — still validates and still publishes, and this reader
# could therefore ship before the writer did.
#   Member | Trial Hrid | Team | Role | Slot | Guild Id | Generated At |
#                                     Loadout Id | Loadout | Loadout Name
# `Loadout Name` was appended on 2026-09-18 and is the template's curated label for
# the recommendation — "Fire DPS (Blazing)", not a titlecased role. It rides on the
# ROW rather than inside the loadout blob because two different templates can hash to
# one loadout id, and then one id would carry two rightful names.
#
# Checked by combat._validate_combat_header ONLY for the columns the header ACTUALLY
# HAS, and only when the header is wider than seven — an entry declared here for a
# column a narrower supported tab does not carry is skipped, not failed, because
# otherwise declaring col 9 would refuse the nine-wide tab that is live today. What
# still refuses a drifted writer is that the columns that ARE present are checked by
# equals, exactly as the required cells are: a NINE-wide tab whose eighth cell is not
# 'Loadout Id' is a drifted writer, not an old one, and guessing which is how the
# wrong JSON gets attributed to the wrong column. What refuses a TORN writer is
# COMBAT_ACCEPTED_WIDTHS below.
#
# `Loadout Id` is a content-derived 'ld_' + 12 hex digits; `Loadout` is the canonical
# JSON of the recommendation itself. It is THE RECOMMENDATION, never an observation of
# what a member is wearing, and it deliberately carries no enhancement levels and no
# ability levels — those come from the opt-in private-profile upload and have no
# business on a public sheet. The canonicalisation rule lives in exactly one file,
# SCLIRoster's optimizer/src/publish/loadout.js; nothing here recomputes it.
COMBAT_OPTIONAL_HEADERS = {
    7: ("equals", "Loadout Id"),
    8: ("equals", "Loadout"),
    9: ("equals", "Loadout Name"),
}

# The widths the writer has ever emitted: seven (pre-2026-09-15), nine (the loadout
# pair) and ten (the loadout NAME, 2026-09-18). Checked as an ALLOW-LIST rather than
# as a maximum, because the interesting failure is not a tab that is too wide — it is
# a tab that is EIGHT wide, which is not an old writer but a torn one, and accepting
# it would attribute a loadout id to a column with no JSON beside it.
#
# Seven never reaches the check at all (the branch is width-gated above seven); it is
# named here as documentation of the supported set rather than as a live test.
COMBAT_ACCEPTED_WIDTHS = (7, 9, 10)

# The TEN SKILLING buildings, hrid -> trial skill name, transcribed from the prose
# list above GUILD_BUILDING_LEVELS. Nothing else belongs here: the seven combat
# buildings (dojo, armory, gym, archery_range, mystical_study, dining_room, library),
# the two encampments and the four utility buildings (guild_hall, builders_hall,
# treasury, archives) grant no SKILLING level and so cannot enter this model. They
# are not dropped either — buildings.parse_buildings keeps every unmapped hrid in
# GuildBuildings.other_levels, so the data exists for the combat optimiser in
# ~/pie/SCLIRoster and for the reward multipliers, once their per-level rules are
# confirmed. An hrid the game adds later lands there too, counted, never silent.
BUILDING_HRID_TO_SKILL = {
    "/guild_buildings/dairy_barn": "Milking",
    "/guild_buildings/garden": "Foraging",
    "/guild_buildings/log_shed": "Woodcutting",
    "/guild_buildings/forge": "C.Smithing",
    "/guild_buildings/workshop": "Crafting",
    "/guild_buildings/sewing_parlor": "Tailoring",
    "/guild_buildings/kitchen": "Cooking",
    "/guild_buildings/brewery": "Brewing",
    "/guild_buildings/laboratory": "Alchemy",
    "/guild_buildings/observatory": "Enhancing",
}

# Staleness for a Buildings capture deliberately REUSES ROSTER_MAX_AGE_DAYS rather
# than adding a twin. A building level changes far more slowly than a member's own
# levels, so a threshold tuned for the roster is conservative here, and a second
# constant would be a second thing to drift. Like that one it is a BANNER threshold
# and not a cutoff: the tab is written only when a member running the module opens
# the guild panel, and an old capture is still better data than the zeros it replaces.

# --- Guild shrines (guild-wide SPEED / EFFICIENCY buffs) ---------------------
# NEW 2026-08-11: "Shrine buffs now apply inside guild Trials". Before the patch the
# shrines were irrelevant here and config said so — "plus the force/tempo shrines —
# none of which grants a skill level" — which was true and beside the point: they do
# not grant LEVELS, they grant efficiency and action speed, and those enter the race
# just as surely.
#
# Authoritative game data (cowstuff milkyway_client_info.json -> guildBuffDetailMap,
# game version v1.20260715.0). Each shrine carries TWO buffs, one flagged
# isCombat=true and one false; only the skilling side is modelled. Values follow the
# same in-game rule as the buildings, flatBoost + (level-1)*flatBoostLevelBonus with
# the two equal, so the grant is simply per_level * level. Verbatim example:
#     {"hrid": "/guild_buffs/force_skilling", "shrineHrid": "/guild_shrines/force",
#      "isCombat": false,
#      "buffs": [{"typeHrid": "/buff_types/efficiency",
#                 "flatBoost": 0.005, "flatBoostLevelBonus": 0.005}]}
#
# ONLY TWO OF THE FIVE REACH THE TIER RACE, and getting this wrong in either
# direction would be a silent modelling error:
#   force   -> /buff_types/efficiency     -> work_power        MODELLED
#   tempo   -> /buff_types/action_speed   -> action_seconds    MODELLED
#   rarity  -> /buff_types/rare_find      -> LOOT only         not modelled
#   spirit  -> /buff_types/essence_find   -> LOOT only         not modelled
#   scholar -> /buff_types/wisdom         -> XP only           not modelled
# The three unmodelled entries are listed anyway, with their post-patch values, so
# that "we considered it and it does not affect the race" is on the record rather
# than inferred from absence.
#
# THE PATCH NOTES ARE THE CROSS-CHECK. "Rare Find 1% -> 1.5% per level, Essence Find
# 2% -> 3% per level" matches the pre-patch dump's rare_find 0.01 and essence_find
# 0.02 exactly, which (a) confirms the per-level reading above and (b) tells us Force
# and Tempo were NOT re-tuned — only admitted into trials. So the 0.005 figures are
# current even though the dump predates the patch.
GUILD_SHRINE_NAMES = {
    "force": "Shrine of Force",
    "tempo": "Shrine of Tempo",
    "spirit": "Shrine of Spirit",
    "rarity": "Shrine of Rarity",
    "scholar": "Shrine of Scholar",
}
# shrine key -> (in-game buff type, value per shrine level, model channel or None).
# The channel is what trials.guild_shrine_bonuses dispatches on; None means the buff
# is real but does not touch the tier race.
GUILD_SHRINE_SKILLING_BUFFS = {
    "force": ("efficiency", 0.005, "efficiency"),
    "tempo": ("action_speed", 0.005, "speed"),
    "rarity": ("rare_find", 0.015, None),
    "spirit": ("essence_find", 0.03, None),
    "scholar": ("wisdom", 0.005, None),
}
GUILD_SHRINE_MAX_LEVEL = 20

# --- The mechanic, ANSWERED 2026-08-31; and why there are now TWO maps -------
# The open question that stood here — does the shrine LEVEL the guild buys with
# guild points multiply a member's stats, or the separately-bought BUFF level? —
# is CLOSED, and the answer is neither alone: **the guild's shrine level is a CAP,
# and each member's own purchase is what reaches the rate.** The scripted roster
# tab carries that purchase per member (`shrine_<name>_skilling`), and the live
# tabs settle it beyond argument: SC's members hold force levels 0..4 with a mean
# of 2.99, against the flat 1 this map used to lend everybody. A single guild-wide
# grant cannot produce a spread.
#
# So the one map has become two, with two different jobs. Conflating them is the
# mistake this comment exists to prevent, because both are "the guild's shrine
# levels" in English and they are not the same number:
#
#   GUILD_SHRINE_LEVELS  the MODELLED guild-wide levels. Read by
#                        trials.guild_shrine_level / guild_shrine_bonuses, which
#                        serve exactly two callers: the ROLLBACK path
#                        (ROSTER_USE_SHRINES = False restores the guild-wide read
#                        and simulate_race's once-per-race hoist, bit-for-bit) and
#                        the per-shrine FALLBACK for a member whose roster column
#                        is blank. It stays at force 1 / tempo 1 — the 2026-07-22
#                        guild_updated capture — because that is what makes the
#                        rollback bit-identical, and because a blank column tells
#                        us nothing about that member and reading it as "at the
#                        cap" would be optimistic about the one case we cannot see.
#
#   GUILD_SHRINE_CAPS    the guild's CAP, per guild. Feeds the two page probes
#                        (trials.probe_shrine_upgrade and probe_shrine_adoption)
#                        and NOTHING in the rate model.
#
# NB the 2026-07-22 capture is therefore also stale AS A CAP: members are observed
# at force 4 on SC, and a member cannot exceed the cap, so SC's shrine level has
# risen to at least 4 since that capture. The caps below are the only current
# evidence this repo holds.
GUILD_SHRINE_LEVELS = {
    "force": 1,
    "tempo": 1,
    "spirit": 0,
    "rarity": 0,
    "scholar": 0,
}

# Each guild's shrine CAP, derived from the observed per-member MAXIMUM on that
# guild's roster tab (2026-09-01, SC 107 members / LI 105). A member cannot buy
# past the cap, so the maximum is a FLOOR on it and not a measurement of it: where
# nobody has bought anything the floor is 0 and the true cap is unknown, which is
# exactly the rarity row on both guilds. The probes read that honestly — a cap of 0
# prices the first level, which is the right question for an unbought shrine.
#
# Split per guild because SC and LI have diverged, which the old single map's own
# comment named as the trigger for splitting it. Full distributions in
# research/roster-as-primary-source.md §4.
GUILD_SHRINE_CAPS = {
    #        force  tempo  spirit  rarity  scholar
    "sc": {"force": 4, "tempo": 4, "spirit": 2, "rarity": 0, "scholar": 2},
    "li": {"force": 3, "tempo": 3, "spirit": 1, "rarity": 0, "scholar": 1},
}


def shrine_caps(guild: str) -> dict[str, int]:
    """One guild's shrine caps ("sc" | "li").

    Raises KeyError on an unknown key rather than falling back, for the same reason
    :func:`party_cap` does: a typo'd guild key quietly pricing the other guild's
    upgrade is the class of silent wrongness this repo keeps losing days to.
    """
    try:
        return GUILD_SHRINE_CAPS[guild]
    except KeyError:
        raise KeyError(
            f"no shrine caps configured for guild {guild!r}; "
            f"known guilds: {sorted(GUILD_SHRINE_CAPS)}"
        ) from None

# Guild-point cost to REACH each shrine level (guildShrineDetailMap guildPointCosts,
# verbatim; all five shrines share one ladder). Note it is exactly DOUBLE the
# building ladder at every level — which, with the measured effect being a fraction
# of a tier even at level 20, is what makes shrines a poor guild-point investment
# beside buildings. See research/guild-shrines.md §5 for the numbers.
GUILD_SHRINE_POINT_COSTS = {
    1: 1000,     2: 1350,     3: 1800,     4: 2450,     5: 3300,
    6: 4500,     7: 6050,     8: 8150,     9: 11050,   10: 14900,
    11: 20100,  12: 27150,   13: 36650,   14: 49450,   15: 66800,
    16: 90150,  17: 121700,  18: 164300,  19: 221800,  20: 299450,
}
# Master switch for the patch note "Shrine buffs now apply inside guild Trials".
# False restores the pre-patch race exactly (bit-identical rates), which is also the
# one-line rollback if a capture ever shows the buffs are excluded after all.
SHRINE_BUFFS_APPLY_IN_TRIALS = True

# --- Upgrade payback ("weeks to return") -------------------------------------
# A building upgrade is a ONE-OFF spend of guild points that only earns anything
# back in the weeks its own skill is drawn. The weekly draw picks 4 of the 10
# skilling trials, so any one skill comes up in 4/10 of weeks — once every 2.5
# weeks on average. That converts a lump-sum cost into a payback period:
#     draws_to_return = total_cost / points_gained_per_draw
#     weeks_to_return = draws_to_return * TRIAL_WEEKS_BETWEEN_DRAWS
# See trials.upgrade_payback_weeks and the trials page's upgrade section.
TRIAL_SKILLS_PER_WEEK = 4      # the weekly draw picks four of the ten skills
TRIAL_WEEKS_BETWEEN_DRAWS = len(SKILLS) / TRIAL_SKILLS_PER_WEEK   # 10/4 = 2.5
# WORKING ASSUMPTION (optimistic, and deliberately so — flagged on the page): the
# bought tier is assumed to hold EVERY time the skill is drawn, so every draw is
# worth the full points_gained. In reality the roster, the sign-ups and the
# community buffs all move week to week, and the party that earns the bump may not
# turn out. Treat the payback as the BEST case, not a promise.

# --- TARGET_SCALE (neutral: the confirmed TotalWork formula carries no scale) -
# Superseded 2026-07-17. The old lab-mirror targets were single-player-scaled
# and needed an empirical fudge factor (TARGET_SCALE=30) to land 20-member
# parties in SC's observed tier 9-11 band. Orvel's confirmed formula
# `TotalWork = DifficultyLevel * 400 * (1 + N/100)` bakes the true scaling into
# the 400 coefficient (TIER_TARGET_PER_LEVEL) and the (1 + N/100) headcount
# term, so no separate scale is applied: TARGET_SCALE is pinned to 1.0. The
# constant and its plumbing are retained (simulate_race / the optimizer accept
# an override) so a future recalibration can still sweep it if needed.
TARGET_SCALE = 1.0

# Which family/back cape group covers each trial skill is implicit in the model
# (efficiency for gathering/alchemy, speed for enhancing); see trials.py.
