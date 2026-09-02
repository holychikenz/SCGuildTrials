"""Unit tests for src/gear.py. No network access.

Four hazards, in order of how quietly each would fail:

  1. **The item table drifting from the catalogue.** ``GEAR_STATS`` is
     transcribed, and a wrong digit in it is a silent mispricing of a real
     member, so it is REGENERATED from ``research/item-stats.json`` and compared
     — the discipline ``config.TOOL_STATS`` and ``ENHANCEMENT_MULT_TABLE`` keep.
  2. **A loot or XP channel reaching a rate model.** The catalogue also carries
     ``<skill>RareFind``, ``<skill>Experience``, ``skillingEssenceFind``,
     ``taskSpeed`` and ``drinkConcentration``. None may appear.
  3. **Blank collapsing into empty.** A blank cell ("we did not look") and
     ``{"items":[]}`` ("we looked, they wore none") are different claims and the
     audit counts them apart.
  4. **The ownership rules being applied to the wrong slot.** Each of the four
     policies is pinned separately, because they disagree with one another
     deliberately: capes and family pieces ARE imputed, accessories never are,
     and garments follow the manual tick.
"""

import json
import re

import pytest

from src import config, gear
from src.reader import MemberRow, SkillEntry


# ---------------------------------------------------------------------------
# 1 + 2: the table against the catalogue
# ---------------------------------------------------------------------------
_RACE_STAT = re.compile(r"(Speed|Efficiency|enhancingSuccess|gatheringQuantity)$")
_EXCLUDED_SLOTS = {"trinket", "pouch"}


def _regenerate_from_catalogue() -> dict:
    """What GEAR_STATS must equal, built from the JSON the same way it was."""
    catalogue = json.load(open("research/item-stats.json"))["items"]
    out = {}
    for hrid, item in catalogue.items():
        slot = item.get("slot") or ""
        if slot.endswith("_tool") or slot in _EXCLUDED_SLOTS:
            continue
        stats = {
            k: v for k, v in (item.get("noncombatStats") or {}).items()
            if _RACE_STAT.search(k)
        }
        if not stats:
            continue
        bonuses = item.get("noncombatEnhancementBonuses") or {}
        out[hrid] = (
            item["name"],
            slot,
            {k: (round(v, 12), round(bonuses.get(k, 0.0), 12))
             for k, v in stats.items()},
        )
    return out


def test_gear_table_matches_item_stats_json():
    """Transcription is checked, not trusted. Twin of test_tool_table_*."""
    assert gear.GEAR_STATS == _regenerate_from_catalogue()


def test_gear_table_is_the_expected_size():
    """39 items: 8 capes, 10 tops, 10 bottoms, 4 family pieces, 7 accessories.

    A bare count, so that an item quietly vanishing from the table shows up here
    rather than as a member losing a bonus nobody was looking at.
    """
    assert len(gear.GEAR_STATS) == 39
    by_slot = {}
    for _, slot, _ in gear.GEAR_STATS.values():
        by_slot[slot] = by_slot.get(slot, 0) + 1
    assert by_slot == {
        "back": 8, "body": 10, "legs": 10,
        "feet": 1, "head": 1, "off_hand": 1, "hands": 1,
        "neck": 3, "ring": 2, "earrings": 2,
    }


def test_gear_table_carries_no_loot_or_xp_stats():
    """A loot or XP buff must never enter a RATE model.

    The same rule ``guild_shrine_bonuses`` applies to the Rarity, Spirit and
    Scholar shrines and ``TOOL_STATS`` applies to RareFind / Experience. The
    ``trinket`` and ``pouch`` slots are refused wholesale: taskSpeed is the TASK
    BOARD's action speed and not a trial's, and the Guzzling Pouch — the seventh
    most-seen item in the whole union, 82 members — buffs drinks.
    """
    forbidden = ("Experience", "RareFind", "EssenceFind", "taskSpeed",
                 "drinkConcentration")
    for hrid, (_, slot, stats) in gear.GEAR_STATS.items():
        assert slot not in _EXCLUDED_SLOTS, hrid
        for stat in stats:
            assert not any(f in stat for f in forbidden), (hrid, stat)


def test_every_stat_name_has_a_channel():
    """STAT_CHANNELS must cover the table, or an item silently loses a bonus."""
    for hrid, (_, _, stats) in gear.GEAR_STATS.items():
        for stat in stats:
            assert stat in gear.STAT_CHANNELS, (hrid, stat)


def test_the_four_family_pieces_tile_the_ten_skills():
    """Exactly one of feet/head/off_hand/hands covers each skill, 3+2+3+2.

    This is what makes the pre-gear model's single unconditional
    ``ARMOUR_EFFICIENCY_PLUS7`` and the per-item resolution comparable at all: if
    two pieces covered one skill the change would silently double a term, and if
    none did it would silently drop one.
    """
    for skill in config.SKILLS:
        covering = [
            slot for slot in gear.FAMILY_SLOTS
            if gear.ITEMS_IN_SLOT_FOR_SKILL.get((slot, skill))
        ]
        assert len(covering) == 1, (skill, covering)


def test_the_four_cape_families_tile_the_ten_skills():
    """And each skill's back slot offers exactly its family's plain and ★ twin."""
    for skill in config.SKILLS:
        capes = gear.ITEMS_IN_SLOT_FOR_SKILL.get((gear.CAPE_SLOT, skill), [])
        assert len(capes) == 2, (skill, capes)
        assert sum(1 for h in capes if h.endswith("_refined")) == 1, capes


def test_shipped_constants_are_reproduced_at_the_assumed_level():
    """The per-item table must agree with the constants it replaces, at +7 / +3.

    Not a coincidence to be discovered later: ``ARMOUR_EFFICIENCY_PLUS7`` IS
    Collector's Boots at +7, and the whole change is credible only if the new
    table reproduces the old number when handed the old assumption. A failure
    here means the transcription or the enhancement rule is wrong, not that the
    constants are stale.
    """
    plus7 = config.ENHANCEMENT_ASSUMED_LEVEL
    boots = gear.item_terms("/items/collectors_boots", "Milking", plus7)
    assert boots["efficiency"] == pytest.approx(config.ARMOUR_EFFICIENCY_PLUS7)
    gloves = gear.item_terms("/items/enchanted_gloves", "Enhancing", plus7)
    assert gloves["speed"] == pytest.approx(config.GLOVES_ENHANCING_SPEED_PLUS7)
    top = gear.item_terms("/items/foragers_top", "Foraging", plus7)
    assert top["efficiency"] == pytest.approx(config.ARMOUR_EFFICIENCY_PLUS7)
    cape = gear.item_terms("/items/gatherer_cape", "Milking", 3)
    assert cape["speed"] == pytest.approx(config.CAPE_SPEED_PLUS3)


def test_enhancers_garments_grant_speed_not_efficiency():
    """The catalogue's channel, retiring a documented simplification.

    ``trials.member_bonuses`` says today that it "deliberately treats top/bot as
    efficiency uniformly" while noting the game grants the Enhancer's pieces
    enhancingSpeed. Following the catalogue is the decision; this pins it.
    """
    for hrid in ("/items/enhancers_top", "/items/enhancers_bottoms"):
        terms = gear.item_terms(hrid, "Enhancing", 7)
        assert set(terms) == {"speed"}, (hrid, terms)


def test_the_generic_necklace_stats_reach_every_skill_including_enhancing():
    """A DECISION, pinned so that reversing it is a visible edit.

    The catalogue calls skillingSpeed / skillingEfficiency "generic, applies to
    all skilling actions", and enhancing is a skilling action. It is the reading
    of an unverified generic and it affects the 117 members wearing a
    Philosopher's Necklace — see research/per-item-gear.md §6.4.
    """
    for skill in config.SKILLS:
        terms = gear.item_terms("/items/philosophers_necklace", skill, 3)
        assert set(terms) == {"speed", "efficiency"}, skill


def test_gathering_quantity_reaches_only_the_gathering_skills():
    for skill in config.SKILLS:
        terms = gear.item_terms("/items/philosophers_ring", skill, 5)
        if skill in config.GATHERING_SKILLS:
            assert set(terms) == {"gathering"}, skill
        else:
            assert terms == {}, skill


# ---------------------------------------------------------------------------
# 3: the cell parser
# ---------------------------------------------------------------------------
def test_blank_is_not_empty():
    """The distinction apps-script/profiles/README.md calls out by name.

    Blank means we did not look (or the member hides their gear); ``{"items":[]}``
    means we looked and they wore none of the tracked set. Collapsing the two
    would erase the only signal separating a card never opened from one
    deliberately withheld.
    """
    assert gear.parse_gear_cell("") is None
    assert gear.parse_gear_cell("   ") is None
    assert gear.parse_gear_cell('{"items":[]}') == {}


def test_parses_levels_and_keeps_zero_apart_from_unknown():
    """0 is a real enhancement level that 34 live observations hold."""
    cell = gear.parse_gear_cell(
        '{"items":[{"hrid":"/items/philosophers_necklace","level":0},'
        '{"hrid":"/items/gatherer_cape"}]}'
    )
    assert cell == {"/items/philosophers_necklace": 0, "/items/gatherer_cape": None}


def test_unknown_hrids_are_kept_for_the_audit_not_dropped():
    cell = gear.parse_gear_cell('{"items":[{"hrid":"/items/new_thing","level":3}]}')
    assert cell == {"/items/new_thing": 3}
    # ... and contribute nothing to any skill.
    assert gear.item_terms("/items/new_thing", "Milking", 3) == {}


@pytest.mark.parametrize("text", [
    "not json",
    '["items"]',
    '{"gear":[]}',
    '{"items":[{"level":3}]}',
])
def test_a_cell_that_will_not_parse_raises_its_own_error(text):
    """Its own type, because the caller's response is specific: count, degrade,
    and do NOT take the build down — the cell may hold months of captures."""
    with pytest.raises(gear.GearParseError):
        gear.parse_gear_cell(text)


# ---------------------------------------------------------------------------
# 4: the ownership rules
# ---------------------------------------------------------------------------
def _member(gear_cell=None, top=False, bot=False):
    return MemberRow(
        name="T", main_classes="", flex="", flex_levels=[],
        skills={
            s: SkillEntry(level=100, tool=False, top=top, bot=bot, house=4)
            for s in config.SKILLS
        },
        gear=gear_cell,
    )


_STATS = gear.ImputationStats(
    guild_key="t",
    cape_speed=0.075,
    cape_n=51,
    family_level={"/items/collectors_boots": 6.3, "/items/red_culinary_hat": 6.2,
                  "/items/eye_watch": 5.9, "/items/enchanted_gloves": 5.7},
    family_n={"/items/collectors_boots": 50, "/items/red_culinary_hat": 46,
              "/items/eye_watch": 47, "/items/enchanted_gloves": 44},
    garment_level=5.33,
    garment_n=33,
)


def test_accessories_are_never_imputed():
    """The rarest items in the game must not be assumed onto anybody.

    With nothing observed, the only SPEED a member can be credited is the imputed
    cape — plus, on Enhancing alone, the imputed Enchanted Gloves, which are the
    one family piece whose channel is speed rather than efficiency. And no
    ``gathering`` at all on any skill, because the rings and earrings that carry
    it are accessories and accessories are never imputed.
    """
    terms = gear.resolve(_member(), _STATS)
    for skill in config.SKILLS:
        speed, _, _, gathering = terms[skill]
        expected = _STATS.cape_speed
        if skill == "Enhancing":
            expected += gear.item_terms("/items/enchanted_gloves", skill, 6)["speed"]
        assert speed == pytest.approx(expected), skill
        assert gathering == 0.0, skill


def test_an_inert_item_in_a_slot_scores_zero_without_a_branch():
    """Necklace of Wisdom is XP; Ring of Rare Find is loot. 41 live members wear
    one. Neither is in GEAR_STATS, so rule 2's accessory case handles it."""
    worn = _member({"/items/necklace_of_wisdom": 5, "/items/ring_of_rare_find": 3})
    bare = _member()
    assert gear.resolve(worn, _STATS) == gear.resolve(bare, _STATS)


def test_the_cape_is_imputed_on_skills_the_observed_cape_does_not_cover():
    """A Gatherer Cape says nothing about the Culinary one: the back slot can
    only ever show the one worn (research/per-item-gear.md §6.2)."""
    m = _member({"/items/gatherer_cape_refined": 3})
    terms = gear.resolve(m, _STATS)
    observed = gear.item_terms("/items/gatherer_cape_refined", "Milking", 3)["speed"]
    assert terms["Milking"][0] == pytest.approx(observed)
    assert terms["Cooking"][0] == pytest.approx(_STATS.cape_speed)


def test_a_family_piece_is_imputed_at_its_own_guild_mean_level():
    m = _member()
    terms = gear.resolve(m, _STATS)
    expected = gear.item_terms("/items/collectors_boots", "Milking", 6)["efficiency"]
    assert terms["Milking"][1] == pytest.approx(expected)


def test_family_piece_imputation_can_be_switched_off(monkeypatch):
    """GEAR_IMPUTE_FAMILY_PIECE = False is the one line that reverses this
    change's largest judgement call — see config's note and §3.1."""
    monkeypatch.setattr(config, "GEAR_IMPUTE_FAMILY_PIECE", False)
    terms = gear.resolve(_member(), _STATS)
    assert terms["Milking"][1] == 0.0


def test_a_garment_needs_the_tick_or_the_sighting():
    """Neither ticked nor seen -> no garment. The rule §3.3's cross-tabulation
    justifies: the tick is a near-perfect superset of the sighting."""
    assert gear.resolve(_member(), _STATS)["Foraging"][1] == pytest.approx(
        gear.item_terms("/items/collectors_boots", "Foraging", 6)["efficiency"]
    )  # boots only, no garment

    ticked = gear.resolve(_member(top=True), _STATS)["Foraging"][1]
    seen = gear.resolve(_member({"/items/foragers_top": 8}), _STATS)["Foraging"][1]
    bare = gear.resolve(_member(), _STATS)["Foraging"][1]
    assert ticked > bare
    assert seen > bare
    # Seen at +8 beats imputed at the pooled mean of 5.33 -> 5.
    assert seen > ticked


def test_a_garment_seen_but_not_ticked_is_owned():
    """Four cases in 1,900 live (member, skill) pairs. They are ownership the
    officers' tab missed, not noise."""
    seen = gear.resolve(_member({"/items/foragers_top": 5}), _STATS)
    bare = gear.resolve(_member(), _STATS)
    assert seen["Foraging"][1] > bare["Foraging"][1]


def test_best_in_slot_wins_when_the_union_holds_two():
    """DORMANT today — no live member shows two items in one slot — and
    implemented so that the moment the union accumulates, the answer is the best
    piece rather than whichever the dict yielded first."""
    both = _member({
        "/items/philosophers_necklace": 3,
        "/items/necklace_of_speed": 3,
    })
    only_philo = _member({"/items/philosophers_necklace": 3})
    assert gear.resolve(both, _STATS) == gear.resolve(only_philo, _STATS)


def test_gear_hidden_members_are_not_a_special_case():
    """`{}` (looked, wore none) and None (blank) resolve identically, and both
    identically to a member the roster never saw. §6.3: there is no `hidden`
    branch anywhere in the module."""
    assert gear.resolve(_member({}), _STATS) == gear.resolve(_member(None), _STATS)


def test_gathering_can_be_taken_out_of_the_rate(monkeypatch):
    """Isolates config.py §1177's open question, which the flat constant could
    not: gatheringQuantity is a different buff type from doubleProgressChance."""
    m = _member({"/items/philosophers_ring": 5, "/items/philosophers_earrings": 5})
    assert gear.resolve(m, _STATS)["Milking"][3] > 0.0
    monkeypatch.setattr(config, "GEAR_GATHERING_IN_RATE", False)
    assert gear.resolve(m, _STATS)["Milking"][3] == 0.0


# ---------------------------------------------------------------------------
# The imputation statistics
# ---------------------------------------------------------------------------
def test_a_statistic_below_the_floor_is_refused():
    """An imputation built on two observations is worse than the assumption it
    replaces, because it LOOKS measured."""
    cells = [{"/items/gatherer_cape": 3}, {"/items/culinary_cape": 5}]
    stats = gear.measure(cells, "t")
    assert stats.cape_n == 2
    assert stats.cape_speed is None
    # ... and the resolver then falls back to the shipped constant.
    terms = gear.resolve(_member(), stats)
    assert terms["Milking"][0] == pytest.approx(config.CAPE_SPEED_PLUS3)


def test_a_refused_family_statistic_falls_back_to_the_assumed_level():
    """Which reproduces ARMOUR_EFFICIENCY_PLUS7 exactly — the pre-gear value."""
    stats = gear.measure([], "t")
    terms = gear.resolve(_member(), stats)
    assert terms["Milking"][1] == pytest.approx(config.ARMOUR_EFFICIENCY_PLUS7)


def test_blank_and_empty_cells_contribute_nothing_to_the_statistics():
    cells = [None, {}] * 40
    stats = gear.measure(cells, "t")
    assert (stats.cape_n, stats.garment_n, stats.family_n) == (0, 0, {})


def test_the_cape_statistic_averages_bonuses_not_levels():
    """Pooling levels would need a base to apply them to, and the plain/★ split
    (0.05 against 0.058, at 73% refined) makes that choice arbitrary."""
    cells = [{"/items/gatherer_cape_refined": 3}] * 20
    stats = gear.measure(cells, "t")
    expected = gear.item_terms("/items/gatherer_cape_refined", "Milking", 3)["speed"]
    assert stats.cape_speed == pytest.approx(expected)
