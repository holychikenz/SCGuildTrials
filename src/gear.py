"""Per-item gear: the `gearSeen` union, read as a rate model.

A THIRD per-member source, and the first that is not a table of numbers but a
table of *things owned*. `apps-script/profiles/Code.gs` writes one column at the
tail of each roster tab -- `gearSeen`, the UNION of every capture of a member's
gear, keyed on hrid, keeping the higher enhancement level. This module turns that
union into the speed / efficiency / success / gathering terms
``trials.member_bonuses`` needs.

WHY THIS IS ITS OWN MODULE. It replaces five flat constants that assert the same
equipment of every member -- ``CAPE_SPEED_PLUS3``, ``ARMOUR_EFFICIENCY_PLUS7``
three times over, and ``GEAR_DOUBLE_CHANCE`` -- and supplies one term that was
never modelled at all: the neck slot, which is the largest single row in
``config.RISK_SIGMA_SYSTEMATIC``'s budget at 0.0081-0.0110 of a ~0.0123 total.
Doing that needs a 39-item catalogue, a stat-name-to-channel mapping, a per-slot
ownership policy and three per-guild imputation statistics. None of that belongs
in ``trials.py``, which is the RACE, nor in ``roster.py``, which is a parser.

THE ONE THING TO KNOW BEFORE EDITING. The resolved terms are computed ONCE per
(member, skill) in the parent process and stored on ``MemberRow.gear_bonuses``;
``member_bonuses`` then reads a dict. Resolving inside ``member_bonuses`` would be
wrong three ways, and the plan (§2) argues each: it is the hottest loop in the
project (``_prepare_member``'s docstring records 22.3 MILLION calls per pipeline
to compute ~1,200 distinct values); it would need the per-guild statistics as
module state, which ``config.BUILD_PARALLEL``'s note warns against because
``trials.community_buff_level`` already rebinds globals on ``trials``; and
recomputing a float sum 22 million times risks the re-association
``_prepare_member`` documents, where ONE ULP in a party rate sends the search down
a different path.

No network, no I/O, no dependency on ``research/`` at runtime: ``GEAR_STATS`` is
TRANSCRIBED from ``research/item-stats.json`` and regenerated and compared by
``tests/test_gear.py::test_gear_table_matches_item_stats_json`` -- the same
discipline ``config.TOOL_STATS`` and ``ENHANCEMENT_MULT_TABLE`` already keep.

Rules, measurements and the one judgement call this module encodes:
``research/per-item-gear.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from . import config

# ---------------------------------------------------------------------------
# The catalogue: every race-relevant NON-TOOL item
# ---------------------------------------------------------------------------
# ``hrid -> (display name, slot, {catalogue stat name: (base, per enhancement)})``
# TRANSCRIBED VERBATIM from research/item-stats.json (game version
# v1.20260715.0), merging each item's ``noncombatStats`` with its
# ``noncombatEnhancementBonuses``, and rounded to 12 decimal places for the reason
# config.TOOL_STATS states: it recovers the catalogue's intended decimals from
# upstream float noise (0.005000000000000001 -> 0.005) and is what lets a shipped
# constant reproduce EXACTLY rather than one ULP away.
#
# effectiveStat = base + config.ENHANCEMENT_MULT_TABLE[level] * per, which is
# calibrate._stat's rule and trials.tool_bonus's rule, applied to a third table.
#
# THE STAT NAMES ARE KEPT AS THE CATALOGUE GIVES THEM and expanded to (skill,
# model channel) pairs through STAT_CHANNELS below. Two reasons. The generics --
# ``skillingSpeed``, ``skillingEfficiency``, ``gatheringQuantity`` -- would each
# have to be written out over three to ten skills, turning a readable 39-line
# table into several hundred lines in which a transcription error would be
# invisible. And the expansion is then ONE rule with ONE test, rather than a
# claim repeated 39 times.
#
# WHAT IS DELIBERATELY ABSENT, each for the reason config.TOOL_STATS gives for
# refusing <skill>RareFind and <skill>Experience -- a loot or XP buff must not
# enter a RATE model:
#   * the three task badges (slot ``trinket``) carry ``taskSpeed``, which is the
#     TASK BOARD's action speed and not a trial's;
#   * the pouches (slot ``pouch``) carry ``drinkConcentration``. Note the
#     Guzzling Pouch is the seventh most-seen item in the whole union -- 82
#     members -- and contributes exactly nothing to a race;
#   * every combat item. The union carries some sixty of them (Chaotic Flail,
#     Anchorbound Plate, and so on); none has a race-relevant channel.
# Pinned by test_gear_table_carries_no_loot_or_xp_stats.
GEAR_STATS: dict[str, tuple[str, str, dict[str, tuple[float, float]]]] = {
    "/items/alchemists_bottoms":
        ("Alchemist's Bottoms", "legs", {"alchemyEfficiency": (0.1, 0.002)}),
    "/items/alchemists_top":
        ("Alchemist's Top", "body", {"alchemyEfficiency": (0.1, 0.002)}),
    "/items/artificer_cape":
        ("Artificer Cape", "back", {"cheesesmithingSpeed": (0.05, 0.005), "craftingSpeed": (0.05, 0.005), "tailoringSpeed": (0.05, 0.005)}),
    "/items/artificer_cape_refined":
        ("Artificer Cape ★", "back", {"cheesesmithingSpeed": (0.058, 0.0058), "craftingSpeed": (0.058, 0.0058), "tailoringSpeed": (0.058, 0.0058)}),
    "/items/brewers_bottoms":
        ("Brewer's Bottoms", "legs", {"brewingEfficiency": (0.1, 0.002)}),
    "/items/brewers_top":
        ("Brewer's Top", "body", {"brewingEfficiency": (0.1, 0.002)}),
    "/items/chance_cape":
        ("Chance Cape", "back", {"alchemySpeed": (0.05, 0.005), "enhancingSpeed": (0.05, 0.005)}),
    "/items/chance_cape_refined":
        ("Chance Cape ★", "back", {"alchemySpeed": (0.058, 0.0058), "enhancingSpeed": (0.058, 0.0058)}),
    "/items/cheesemakers_bottoms":
        ("Cheesemaker's Bottoms", "legs", {"cheesesmithingEfficiency": (0.1, 0.002)}),
    "/items/cheesemakers_top":
        ("Cheesemaker's Top", "body", {"cheesesmithingEfficiency": (0.1, 0.002)}),
    "/items/chefs_bottoms":
        ("Chef's Bottoms", "legs", {"cookingEfficiency": (0.1, 0.002)}),
    "/items/chefs_top":
        ("Chef's Top", "body", {"cookingEfficiency": (0.1, 0.002)}),
    "/items/collectors_boots":
        ("Collector's Boots", "feet", {"foragingEfficiency": (0.1, 0.002), "milkingEfficiency": (0.1, 0.002), "woodcuttingEfficiency": (0.1, 0.002)}),
    "/items/crafters_bottoms":
        ("Crafter's Bottoms", "legs", {"craftingEfficiency": (0.1, 0.002)}),
    "/items/crafters_top":
        ("Crafter's Top", "body", {"craftingEfficiency": (0.1, 0.002)}),
    "/items/culinary_cape":
        ("Culinary Cape", "back", {"brewingSpeed": (0.05, 0.005), "cookingSpeed": (0.05, 0.005)}),
    "/items/culinary_cape_refined":
        ("Culinary Cape ★", "back", {"brewingSpeed": (0.058, 0.0058), "cookingSpeed": (0.058, 0.0058)}),
    "/items/dairyhands_bottoms":
        ("Dairyhand's Bottoms", "legs", {"milkingEfficiency": (0.1, 0.002)}),
    "/items/dairyhands_top":
        ("Dairyhand's Top", "body", {"milkingEfficiency": (0.1, 0.002)}),
    "/items/earrings_of_gathering":
        ("Earrings Of Gathering", "earrings", {"gatheringQuantity": (0.02, 0.002)}),
    "/items/enchanted_gloves":
        ("Enchanted Gloves", "hands", {"alchemyEfficiency": (0.1, 0.002), "enhancingSpeed": (0.1, 0.002)}),
    "/items/enhancers_bottoms":
        ("Enhancer's Bottoms", "legs", {"enhancingSpeed": (0.1, 0.002)}),
    "/items/enhancers_top":
        ("Enhancer's Top", "body", {"enhancingSpeed": (0.1, 0.002)}),
    "/items/eye_watch":
        ("Eye Watch", "off_hand", {"cheesesmithingEfficiency": (0.1, 0.002), "craftingEfficiency": (0.1, 0.002), "tailoringEfficiency": (0.1, 0.002)}),
    "/items/foragers_bottoms":
        ("Forager's Bottoms", "legs", {"foragingEfficiency": (0.1, 0.002)}),
    "/items/foragers_top":
        ("Forager's Top", "body", {"foragingEfficiency": (0.1, 0.002)}),
    "/items/gatherer_cape":
        ("Gatherer Cape", "back", {"foragingSpeed": (0.05, 0.005), "milkingSpeed": (0.05, 0.005), "woodcuttingSpeed": (0.05, 0.005)}),
    "/items/gatherer_cape_refined":
        ("Gatherer Cape ★", "back", {"foragingSpeed": (0.058, 0.0058), "milkingSpeed": (0.058, 0.0058), "woodcuttingSpeed": (0.058, 0.0058)}),
    "/items/lumberjacks_bottoms":
        ("Lumberjack's Bottoms", "legs", {"woodcuttingEfficiency": (0.1, 0.002)}),
    "/items/lumberjacks_top":
        ("Lumberjack's Top", "body", {"woodcuttingEfficiency": (0.1, 0.002)}),
    "/items/necklace_of_efficiency":
        ("Necklace Of Efficiency", "neck", {"skillingEfficiency": (0.02, 0.002)}),
    "/items/necklace_of_speed":
        ("Necklace Of Speed", "neck", {"skillingSpeed": (0.04, 0.004)}),
    "/items/philosophers_earrings":
        ("Philosopher's Earrings", "earrings", {"gatheringQuantity": (0.02, 0.002)}),
    "/items/philosophers_necklace":
        ("Philosopher's Necklace", "neck", {"skillingEfficiency": (0.02, 0.002), "skillingSpeed": (0.04, 0.004)}),
    "/items/philosophers_ring":
        ("Philosopher's Ring", "ring", {"gatheringQuantity": (0.02, 0.002)}),
    "/items/red_culinary_hat":
        ("Red Culinary Hat", "head", {"brewingEfficiency": (0.1, 0.002), "cookingEfficiency": (0.1, 0.002)}),
    "/items/ring_of_gathering":
        ("Ring Of Gathering", "ring", {"gatheringQuantity": (0.02, 0.002)}),
    "/items/tailors_bottoms":
        ("Tailor's Bottoms", "legs", {"tailoringEfficiency": (0.1, 0.002)}),
    "/items/tailors_top":
        ("Tailor's Top", "body", {"tailoringEfficiency": (0.1, 0.002)}),
}


# ---------------------------------------------------------------------------
# Catalogue stat name -> (which SKILLS it reaches, which MODEL channel)
# ---------------------------------------------------------------------------
# The expansion rule GEAR_STATS's note defers to, and the same shape
# config.GUILD_SHRINE_SKILLING_BUFFS uses for the same purpose: one table
# mapping the game's own field name onto the model's channel, so a field this
# model must not read is refused BY THE TABLE rather than by never having been
# thought about.
#
# THE THREE GENERICS ARE THE POINT OF THIS TABLE:
#   * ``skillingSpeed`` / ``skillingEfficiency`` -- the catalogue's own semantics
#     block calls these "generic, applies to all skilling actions", and ENHANCING
#     IS A SKILLING ACTION, so both reach all ten. That is a DECISION and it is
#     recorded as one (research/per-item-gear.md §6.4): it is the reading of an
#     unverified generic, it affects the 117 members wearing a Philosopher's
#     Necklace, and it is isolable to this one row if a capture ever refutes it.
#   * ``gatheringQuantity`` reaches the three GATHERING skills only, and lands on
#     the ``gathering`` channel rather than on efficiency. See GATHERING_CHANNEL
#     below for the open question it inherits -- one this module did not create
#     and does not resolve.
#
# ``enhancingSuccess`` appears here for completeness and symmetry with
# config.TOOL_STATS; no non-tool item carries it, so the ``success`` channel of a
# resolved GearTerms is always 0.0 today. Kept because a future item may, and a
# channel that exists in the table cannot be silently misapplied.
_ALL = tuple(config.SKILLS)
_GATHERING = tuple(s for s in config.SKILLS if s in config.GATHERING_SKILLS)

STAT_CHANNELS: dict[str, tuple[tuple[str, ...], str]] = {
    # per-skill speed
    "milkingSpeed":            (("Milking",),      "speed"),
    "foragingSpeed":           (("Foraging",),     "speed"),
    "woodcuttingSpeed":        (("Woodcutting",),  "speed"),
    "cheesesmithingSpeed":     (("C.Smithing",),   "speed"),
    "craftingSpeed":           (("Crafting",),     "speed"),
    "tailoringSpeed":          (("Tailoring",),    "speed"),
    "cookingSpeed":            (("Cooking",),      "speed"),
    "brewingSpeed":            (("Brewing",),      "speed"),
    "alchemySpeed":            (("Bell Farming",), "speed"),
    "enhancingSpeed":          (("Enhancing",),    "speed"),
    # per-skill efficiency
    "milkingEfficiency":       (("Milking",),      "efficiency"),
    "foragingEfficiency":      (("Foraging",),     "efficiency"),
    "woodcuttingEfficiency":   (("Woodcutting",),  "efficiency"),
    "cheesesmithingEfficiency": (("C.Smithing",),  "efficiency"),
    "craftingEfficiency":      (("Crafting",),     "efficiency"),
    "tailoringEfficiency":     (("Tailoring",),    "efficiency"),
    "cookingEfficiency":       (("Cooking",),      "efficiency"),
    "brewingEfficiency":       (("Brewing",),      "efficiency"),
    "alchemyEfficiency":       (("Bell Farming",), "efficiency"),
    "enhancingEfficiency":     (("Enhancing",),    "efficiency"),
    # generics
    "skillingSpeed":           (_ALL,              "speed"),
    "skillingEfficiency":      (_ALL,              "efficiency"),
    "gatheringQuantity":       (_GATHERING,        "gathering"),
    "enhancingSuccess":        (("Enhancing",),    "success"),
}

CHANNELS = ("speed", "efficiency", "success", "gathering")

# ---------------------------------------------------------------------------
# What an UNOBSERVED item in each slot is worth
# ---------------------------------------------------------------------------
# The rules of research/per-item-gear.md §6, as a table rather than as a chain of
# ifs, so that a slot's policy can be read off in one place and a new slot cannot
# be added without stating one.
#
#   "impute-cape"     The skill's covering cape at the guild's POOLED MEAN
#                     EFFECTIVE SPEED. Applies even to a member observed wearing
#                     a DIFFERENT family's cape on a skill that cape does not
#                     cover: the back slot can only ever show the one worn, so a
#                     sighting says nothing about the other three families. It
#                     also applies to a member seen in a non-cape back item (an
#                     Enchanted Cloak, 15 members), which is the cape's analogue
#                     of the Necklace-of-Wisdom case and is deliberately resolved
#                     the OTHER way -- capes are imputed, accessories never are.
#   "impute-item"     Assume owned, at THAT ITEM's per-guild mean level. The four
#                     family pieces, which tile the ten skills 3+2+3+2.
#   "manual-tick"     Owned if and only if the manual tab's top/bot checkbox is
#                     ticked OR the union saw it; level observed where seen, else
#                     the guild's POOLED GARMENT mean level. Pooled because eight
#                     of the eleven observed garments rest on n=1 or n=2, and a
#                     mean of one observation is not a mean (§6.7).
#   "never"           Zero, never imputed. The Philosopher's pieces are the
#                     rarest items in the game and must not be assumed; and this
#                     is what makes an inert item in the slot (Necklace of
#                     Wisdom, Ring of Rare Find -- 41 members between them) score
#                     zero without needing a branch of its own.
SLOT_POLICY: dict[str, str] = {
    "back":     "impute-cape",
    "feet":     "impute-item",
    "head":     "impute-item",
    "off_hand": "impute-item",
    "hands":    "impute-item",
    "body":     "manual-tick",
    "legs":     "manual-tick",
    "neck":     "never",
    "ring":     "never",
    "earrings": "never",
}

# Slots whose imputation is governed by config.GEAR_IMPUTE_FAMILY_PIECE -- the
# one line that reverses this change's largest judgement call. See
# research/per-item-gear.md §3.1: the four pieces are held ALL-OR-NOTHING (48% of
# visible members show none, 37% show all four), and 82 members wear a skilling
# necklace -- proving the capture caught them in skilling kit -- while showing not
# one of the four. The universal grant is kept on the operator's judgement that
# the union has not converged. If that is wrong, half of both guilds is credited
# a 0.1182 efficiency term it does not own.
FAMILY_SLOTS = frozenset({"feet", "head", "off_hand", "hands"})
CAPE_SLOT = "back"
GARMENT_SLOTS = frozenset({"body", "legs"})
ACCESSORY_SLOTS = frozenset({"neck", "ring", "earrings"})


# ---------------------------------------------------------------------------
# Derived lookups, built once at import from GEAR_STATS + STAT_CHANNELS
# ---------------------------------------------------------------------------
def _item_channels(hrid: str) -> dict[str, dict[str, tuple[float, float]]]:
    """``{skill: {channel: (base, per)}}`` for one item.

    Raises KeyError on a stat name STAT_CHANNELS does not know, which is how a
    new catalogue channel announces itself rather than being silently dropped.
    """
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for stat, (skills, channel) in (
        (s, STAT_CHANNELS[s]) for s in GEAR_STATS[hrid][2]
    ):
        base, per = GEAR_STATS[hrid][2][stat]
        for skill in skills:
            out.setdefault(skill, {})[channel] = (base, per)
    return out


ITEM_CHANNELS: dict[str, dict[str, dict[str, tuple[float, float]]]] = {
    hrid: _item_channels(hrid) for hrid in GEAR_STATS
}
SLOT_OF: dict[str, str] = {h: v[1] for h, v in GEAR_STATS.items()}
NAME_OF: dict[str, str] = {h: v[0] for h, v in GEAR_STATS.items()}

# ``(slot, skill) -> [hrid, ...]``: every item in that slot that reaches that
# skill. A LIST because the back slot holds a plain cape and its ★ twin, and the
# neck slot holds three necklaces; ordered by hrid so a tie is resolved
# deterministically rather than by dict insertion.
ITEMS_IN_SLOT_FOR_SKILL: dict[tuple[str, str], list[str]] = {}
for _h in sorted(GEAR_STATS):
    for _skill in ITEM_CHANNELS[_h]:
        ITEMS_IN_SLOT_FOR_SKILL.setdefault((SLOT_OF[_h], _skill), []).append(_h)
del _h, _skill


def effective_stat(base: float, per: float, level: Optional[int]) -> float:
    """``base + ENHANCEMENT_MULT_TABLE[level] * per`` -- the catalogue's own rule.

    The same arithmetic as ``trials.tool_bonus`` and ``calibrate._stat``, in the
    same order, deliberately: three tables now share one rule and a divergence
    between them would be a silent mispricing rather than an error.

    ``level`` None means "owned, level unknown" and is priced at level 0 -- the
    caller is expected to have substituted an imputed level before this point,
    and a None reaching here is the conservative reading rather than a crash.
    """
    if level is None:
        return base
    lv = max(0, min(len(config.ENHANCEMENT_MULT_TABLE) - 1, level))
    return base + config.ENHANCEMENT_MULT_TABLE[lv] * per


def item_terms(hrid: str, skill: str, level: Optional[int]) -> dict[str, float]:
    """``{channel: value}`` this item grants this skill at this level.

    Empty for an item that does not reach the skill at all -- Red Culinary Hat on
    Milking, say -- which is the common case and not an error: the four family
    pieces tile the ten skills, so three of the four are silent on any given one.
    """
    per_skill = ITEM_CHANNELS.get(hrid, {}).get(skill)
    if not per_skill:
        return {}
    return {
        channel: effective_stat(base, per, level)
        for channel, (base, per) in per_skill.items()
    }


# ---------------------------------------------------------------------------
# The cell
# ---------------------------------------------------------------------------
# Three states, and the difference between the last two is the whole reason the
# upstream README says "Blank is not empty":
#
#   BLANK        we did not look, or the member has ``hideWearableItems`` set.
#                Contributes nothing and erases nothing. -> ``None``
#   {"items":[]} we LOOKED and they wore none of the tracked set. A different and
#                weaker claim, and the one the six LI / nine SC gear-hiders
#                actually make. -> ``{}``
#   {"items":[…]} the union. -> ``{hrid: level}``
#
# Collapsing blank into empty would erase the only signal that separates a member
# whose card was never opened from one who declined to show it -- and both of
# those from a member genuinely wearing nothing tracked. Nothing downstream
# currently treats the two differently (both fall to the unobserved rules, by
# decision -- research/per-item-gear.md §6.3, "gear-hidden members are not a
# special case"), but the AUDIT counts them apart, which is how an upstream
# breakage in the writer would be noticed at all.
GearCell = Optional[dict[str, Optional[int]]]


class GearParseError(ValueError):
    """A ``gearSeen`` cell that will not parse.

    Its own type because the caller's response is specific: count it, leave the
    member on the unobserved rules, and do NOT take the build down. The tab is
    machine-written, so an unparseable cell means the writer changed or somebody
    hand-edited a cell that may hold months of captures -- see the "A cell that
    will not parse is left exactly as it is" note in
    ``apps-script/profiles/README.md``.
    """


def parse_gear_cell(text: str) -> GearCell:
    """Parse one ``gearSeen`` cell. See :data:`GearCell` for the three states.

    Levels are kept as ``Optional[int]``: a missing or non-integer ``level`` is
    ``None`` ("owned, level unknown") rather than 0, because 0 is a real
    enhancement level that 34 observations actually hold and the two must not be
    confused. Unknown hrids are kept, not dropped -- the audit needs to name them,
    and :func:`resolve` ignores anything absent from ``GEAR_STATS``.
    """
    text = (text or "").strip()
    if text == "":
        return None
    try:
        obj = json.loads(text)
    except ValueError as exc:
        raise GearParseError(f"not JSON: {text[:80]!r}") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("items"), list):
        raise GearParseError(f'expected {{"items": [...]}}, got {text[:80]!r}')
    out: dict[str, Optional[int]] = {}
    for entry in obj["items"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("hrid"), str):
            raise GearParseError(f"item without an hrid: {entry!r}")
        level = entry.get("level")
        out[entry["hrid"]] = level if isinstance(level, int) else None
    return out


# ---------------------------------------------------------------------------
# The three imputation statistics
# ---------------------------------------------------------------------------
@dataclass
class ImputationStats:
    """What an unobserved item is worth, measured from THIS guild's own union.

    COMPUTED, NOT TRANSCRIBED, and that is the one place this module departs from
    ``config.TOOL_STATS``' discipline. The tool table is a CATALOGUE fact: it is
    true until the game changes, so it is pinned as a constant and tested against
    the JSON. These three are live measurements of a changing guild -- members
    enhance their gear every week -- and a transcribed value would be stale the
    week after it was written. ``research/per-item-gear.md`` §6.7 records the
    figures as of 2026-09-02 so a drift can be noticed.

    PER GUILD, never pooled across the two. SC's family pieces average 1.2-1.5
    enhancement levels above LI's, so one shared statistic would misprice both.

    ``n`` is carried beside every statistic, and a statistic whose support falls
    below ``config.GEAR_MIN_IMPUTE_N`` is REFUSED -- the shipped constant is used
    instead. Eight of the eleven observed garments rest on n=1 or n=2, and a mean
    of one observation is not a mean.
    """

    guild_key: str = ""
    # Pooled mean EFFECTIVE SPEED over every observed cape, not a mean level.
    # Pooling levels would then need a base to apply them to, and the plain/★
    # split (0.05 against 0.058, at 73% refined) makes that choice arbitrary;
    # pooling the finished bonus does not.
    cape_speed: Optional[float] = None
    cape_n: int = 0
    # hrid -> mean observed LEVEL, for the four family pieces. Per item, because
    # each has n=38-50 and they differ from one another by up to 0.5 levels.
    family_level: dict[str, float] = field(default_factory=dict)
    family_n: dict[str, int] = field(default_factory=dict)
    # Pooled mean observed LEVEL over every body/legs garment. Pooled, for the
    # n=1 reason above.
    garment_level: Optional[float] = None
    garment_n: int = 0

    def to_dict(self) -> dict:
        return {
            "guild": self.guild_key,
            "cape_speed": self.cape_speed,
            "cape_n": self.cape_n,
            "family_level": dict(self.family_level),
            "family_n": dict(self.family_n),
            "garment_level": self.garment_level,
            "garment_n": self.garment_n,
        }


def measure(cells: list[GearCell], guild_key: str = "") -> ImputationStats:
    """Measure the three statistics from one guild's parsed ``gearSeen`` cells.

    Takes the CELLS rather than the members so that it can be run against a tab
    without a join -- which is what ``research/scratch/gear_survey.py`` does, and
    what makes this function checkable against a number a human can read off the
    sheet.

    A statistic with support below ``config.GEAR_MIN_IMPUTE_N`` is left None, and
    :func:`resolve` then falls back to the shipped constant. Refusing is the point:
    an imputation built on two observations is worse than the assumption it
    replaces, because it LOOKS measured.
    """
    stats = ImputationStats(guild_key=guild_key)
    cape_bonuses: list[float] = []
    family_levels: dict[str, list[int]] = {}
    garment_levels: list[int] = []

    for cell in cells:
        if not cell:  # blank, or looked-and-wore-none: neither contributes
            continue
        for hrid, level in cell.items():
            slot = SLOT_OF.get(hrid)
            if slot is None or not isinstance(level, int):
                continue
            if slot == CAPE_SLOT:
                # The item's own first channel value, at its own level: the
                # SPEED it actually grants, which is what we are averaging.
                base, per = next(iter(GEAR_STATS[hrid][2].values()))
                cape_bonuses.append(effective_stat(base, per, level))
            elif slot in FAMILY_SLOTS:
                family_levels.setdefault(hrid, []).append(level)
            elif slot in GARMENT_SLOTS:
                garment_levels.append(level)

    floor = config.GEAR_MIN_IMPUTE_N
    stats.cape_n = len(cape_bonuses)
    if stats.cape_n >= floor:
        stats.cape_speed = sum(cape_bonuses) / stats.cape_n
    stats.garment_n = len(garment_levels)
    if stats.garment_n >= floor:
        stats.garment_level = sum(garment_levels) / stats.garment_n
    for hrid, levels in family_levels.items():
        stats.family_n[hrid] = len(levels)
        if len(levels) >= floor:
            stats.family_level[hrid] = sum(levels) / len(levels)
    return stats


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------
# ``body`` reads the manual tab's "top" checkbox and ``legs`` its "bot" -- the
# ownership claim that the union merely corroborates. Measured over both guilds,
# the tick is a near-perfect SUPERSET of the sighting: four cases in 1,900 where
# the union saw a garment nobody ticked (research/per-item-gear.md §3.3). Those
# four are taken as owned, which is why the rule is "ticked OR seen".
_TICK_ATTR = {"body": "top", "legs": "bot"}


@dataclass
class GearAudit:
    """What one guild's gear column said, counted once per build.

    The counting lives here and runs ONCE per guild in the parent, for the reason
    ``trials.ToolAudit``'s docstring gives: ``member_bonuses`` runs ~22 million
    times per pipeline and in child processes under ``BUILD_PARALLEL``, so a
    counter there would be both expensive and unaggregatable.

    ``blank`` and ``looked_and_none`` are counted APART even though nothing
    downstream treats them differently, because an upstream breakage in the
    writer would show up here first: a sudden run of blanks means the userscript
    stopped sending, and a sudden run of empties means it is sending but seeing
    nothing.
    """

    guild_key: str = ""
    visible: int = 0            # members whose union names at least one item
    looked_and_none: int = 0    # `{"items":[]}` -- we looked, they wore none
    blank: int = 0              # blank cell -- we did not look, or gear is hidden
    unparseable: list[str] = field(default_factory=list)   # member names
    unknown_items: dict[str, int] = field(default_factory=dict)
    observed_by_slot: dict[str, int] = field(default_factory=dict)
    imputed_by_slot: dict[str, int] = field(default_factory=dict)
    # Statistics REFUSED for want of support (config.GEAR_MIN_IMPUTE_N), by name.
    refused_statistics: list[str] = field(default_factory=list)
    stats: Optional[ImputationStats] = None

    def to_dict(self) -> dict:
        return {
            "guild": self.guild_key,
            "visible": self.visible,
            "looked_and_none": self.looked_and_none,
            "blank": self.blank,
            "unparseable": list(self.unparseable),
            "unknown_items": dict(self.unknown_items),
            "observed_by_slot": dict(self.observed_by_slot),
            "imputed_by_slot": dict(self.imputed_by_slot),
            "refused_statistics": list(self.refused_statistics),
            "stats": self.stats.to_dict() if self.stats else None,
        }


def _best_in_slot(hrids: list[str], skill: str, cell: dict) -> str:
    """The observed item in one slot worth most to ``skill``.

    THE OPERATOR'S RULE, and currently DORMANT: no member on either guild shows
    two race-relevant items in one slot, so the union has not begun to accumulate
    and this always has exactly one candidate (research/per-item-gear.md §3.2).
    It is implemented for when that changes, because the moment it does, silently
    picking whichever the dict happened to yield first would be a mispricing
    nobody would notice.

    "Worth most" is summed over the item's channels for THIS skill, so
    Philosopher's Necklace -- speed AND efficiency -- beats the single-stat
    necklaces, which is what "best-in-slot" means for these items. Ties break on
    the hrid so the answer is deterministic rather than insertion-ordered.
    """
    return min(
        hrids,
        key=lambda h: (-sum(item_terms(h, skill, cell.get(h)).values()), h),
    )


def resolve(
    member,
    stats: ImputationStats,
    audit: Optional[GearAudit] = None,
) -> dict[str, tuple[float, float, float, float]]:
    """``{skill: (speed, efficiency, success, gathering)}`` for one member.

    The rules of ``research/per-item-gear.md`` §6, applied slot by slot. Called
    ONCE per member in the parent process; ``trials.member_bonuses`` then reads
    the dict. See this module's header for why that is not negotiable.

    Returns a PLAIN dict of plain tuples -- picklable, and a tuple for the reason
    ``_prepare_member`` returns one: the caller unpacks it in the hottest loop in
    the project, where attribute lookups are measurable.

    ``member.gear`` None (a blank cell) and ``{}`` (looked, wore none) behave
    identically here, by decision: a gear-hidden member is NOT a special case and
    follows the unobserved rules exactly. There is no ``hidden`` branch anywhere
    in this module, which is the single largest simplification in the design.
    """
    cell = member.gear or {}
    out: dict[str, tuple[float, float, float, float]] = {}

    for skill in config.SKILLS:
        terms = {"speed": 0.0, "efficiency": 0.0, "success": 0.0, "gathering": 0.0}
        for slot, policy in SLOT_POLICY.items():
            if not _slot_enabled(slot):
                continue
            candidates = ITEMS_IN_SLOT_FOR_SKILL.get((slot, skill), [])
            if not candidates:
                continue  # this slot has nothing to offer this skill
            observed = [h for h in candidates if h in cell]
            if observed:
                hrid = _best_in_slot(observed, skill, cell)
                _add(terms, item_terms(hrid, skill, cell[hrid]))
                _bump(audit, "observed_by_slot", slot)
                continue
            imputed = _impute(slot, policy, skill, candidates, member, stats)
            if imputed:
                _add(terms, imputed)
                _bump(audit, "imputed_by_slot", slot)
        if not config.GEAR_GATHERING_IN_RATE:
            terms["gathering"] = 0.0
        out[skill] = (
            terms["speed"], terms["efficiency"], terms["success"], terms["gathering"]
        )
    return out


def _slot_enabled(slot: str) -> bool:
    """Whether this slot's slice is switched on (the partial-rollback ladder)."""
    if slot == CAPE_SLOT:
        return config.GEAR_USE_CAPE
    if slot in FAMILY_SLOTS:
        return config.GEAR_USE_FAMILY_PIECE
    if slot in GARMENT_SLOTS:
        return config.GEAR_USE_GARMENTS
    if slot in ACCESSORY_SLOTS:
        return config.GEAR_USE_ACCESSORIES
    return True


def _impute(
    slot: str,
    policy: str,
    skill: str,
    candidates: list[str],
    member,
    stats: ImputationStats,
) -> dict[str, float]:
    """What an UNOBSERVED slot is worth. The SLOT_POLICY table, executed."""
    if policy == "never":
        return {}

    if policy == "impute-cape":
        # The pooled mean EFFECTIVE speed, not a level, so there is no base to
        # pick between the plain cape and its ★ twin. Falls back to the shipped
        # constant when the statistic was refused for want of support.
        speed = stats.cape_speed
        if speed is None:
            speed = config.CAPE_SPEED_PLUS3
        return {"speed": speed}

    if policy == "impute-item":
        if not config.GEAR_IMPUTE_FAMILY_PIECE:
            return {}
        # Exactly one family piece covers any given skill -- the four tile the ten
        # 3+2+3+2 -- so a candidate list of one is the expected case, and
        # _best_in_slot's tie-break is not needed here.
        hrid = candidates[0]
        level = stats.family_level.get(hrid)
        if level is None:
            # Statistic refused: fall back to the level the pre-gear model
            # assumed, which reproduces ARMOUR_EFFICIENCY_PLUS7 exactly.
            level = float(config.ENHANCEMENT_ASSUMED_LEVEL)
        return item_terms(hrid, skill, _round_level(level))

    if policy == "manual-tick":
        entry = member.skills.get(skill)
        if entry is None or not getattr(entry, _TICK_ATTR[slot], False):
            return {}   # neither ticked nor seen: no garment
        hrid = candidates[0]
        level = stats.garment_level
        if level is None:
            level = float(config.ENHANCEMENT_ASSUMED_LEVEL)
        return item_terms(hrid, skill, _round_level(level))

    raise ValueError(f"SLOT_POLICY names an unknown policy {policy!r} for {slot!r}")


def _round_level(level: float) -> int:
    """An imputed MEAN level, made an index into ENHANCEMENT_MULT_TABLE.

    ``int(round(...))`` rather than interpolating between two table entries. The
    table is the game's own array and this repo reads it VERBATIM -- see
    ENHANCEMENT_MULT_TABLE's note and ``calibrate._load_multiplier_table``'s two
    asserts -- so interpolating would invent a multiplier the game does not have.
    Rounding half to even is Python's default and is fine here: the choice moves
    an imputed bonus by ~0.002, well inside the imputation's own error.
    """
    return int(round(level))


def _add(terms: dict[str, float], contribution: dict[str, float]) -> None:
    for channel, value in contribution.items():
        terms[channel] += value


def _bump(audit: Optional[GearAudit], field_name: str, key: str) -> None:
    if audit is None:
        return
    counter = getattr(audit, field_name)
    counter[key] = counter.get(key, 0) + 1
