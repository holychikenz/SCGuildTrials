"""The Buildings-tab reader: guarding, routing and refusing.

Fixture-driven and offline — LIVE_SC_CSV below is the real ``SC Buildings`` tab,
captured verbatim on 2026-09-09, so these tests pin the parser against the bytes
Google actually serves rather than against a hand-written idea of them.

Three outcomes are under test and they are deliberately not two: a populated tab, an
EMPTY one (normal — the tabs are created by hand and empty, which is LI's position
today), and a malformed one. Conflating the middle case with either neighbour is the
defect this module's shape exists to prevent.
"""

import pytest

from src import buildings, config
from src.reader import SheetStructureError

# The real SC Buildings tab, 2026-09-09T13:00:53.934Z, byte-for-byte as gviz serves
# it: 23 buildings then 5 shrines, every row stamped with guild id 4.
LIVE_SC_CSV = """\
"Building","Hrid","Kind","Level","Guild Id","Captured At"
"Guild Hall","/guild_buildings/guild_hall","building","8","4","2026-09-09T13:00:53.934Z"
"Builder's Hall","/guild_buildings/builders_hall","building","6","4","2026-09-09T13:00:53.934Z"
"Treasury","/guild_buildings/treasury","building","5","4","2026-09-09T13:00:53.934Z"
"Archives","/guild_buildings/archives","building","0","4","2026-09-09T13:00:53.934Z"
"Skilling Encampment","/guild_buildings/skilling_encampment","building","4","4","2026-09-09T13:00:53.934Z"
"Combat Encampment","/guild_buildings/combat_encampment","building","3","4","2026-09-09T13:00:53.934Z"
"Guild Dairy Barn","/guild_buildings/dairy_barn","building","0","4","2026-09-09T13:00:53.934Z"
"Guild Garden","/guild_buildings/garden","building","0","4","2026-09-09T13:00:53.934Z"
"Guild Log Shed","/guild_buildings/log_shed","building","0","4","2026-09-09T13:00:53.934Z"
"Guild Forge","/guild_buildings/forge","building","0","4","2026-09-09T13:00:53.934Z"
"Guild Workshop","/guild_buildings/workshop","building","0","4","2026-09-09T13:00:53.934Z"
"Guild Sewing Parlor","/guild_buildings/sewing_parlor","building","0","4","2026-09-09T13:00:53.934Z"
"Guild Kitchen","/guild_buildings/kitchen","building","0","4","2026-09-09T13:00:53.934Z"
"Guild Brewery","/guild_buildings/brewery","building","0","4","2026-09-09T13:00:53.934Z"
"Guild Laboratory","/guild_buildings/laboratory","building","0","4","2026-09-09T13:00:53.934Z"
"Guild Observatory","/guild_buildings/observatory","building","1","4","2026-09-09T13:00:53.934Z"
"Guild Dining Room","/guild_buildings/dining_room","building","0","4","2026-09-09T13:00:53.934Z"
"Guild Library","/guild_buildings/library","building","0","4","2026-09-09T13:00:53.934Z"
"Guild Dojo","/guild_buildings/dojo","building","4","4","2026-09-09T13:00:53.934Z"
"Guild Armory","/guild_buildings/armory","building","2","4","2026-09-09T13:00:53.934Z"
"Guild Gym","/guild_buildings/gym","building","1","4","2026-09-09T13:00:53.934Z"
"Guild Archery Range","/guild_buildings/archery_range","building","1","4","2026-09-09T13:00:53.934Z"
"Guild Mystical Study","/guild_buildings/mystical_study","building","2","4","2026-09-09T13:00:53.934Z"
"Shrine of Force","/guild_shrines/force","shrine","5","4","2026-09-09T13:00:53.934Z"
"Shrine of Tempo","/guild_shrines/tempo","shrine","4","4","2026-09-09T13:00:53.934Z"
"Shrine of Spirit","/guild_shrines/spirit","shrine","2","4","2026-09-09T13:00:53.934Z"
"Shrine of Rarity","/guild_shrines/rarity","shrine","0","4","2026-09-09T13:00:53.934Z"
"Shrine of Scholar","/guild_shrines/scholar","shrine","2","4","2026-09-09T13:00:53.934Z"
"""

# What gviz serves for a tab name that DOES NOT EXIST: not an error, and not empty —
# the FIRST tab's content. Measured 2026-09-09 (3518 bytes). This is the whole reason
# the header guard is mandatory rather than defensive, so the test uses the real shape
# of the wrong-tab payload rather than an invented one.
WRONG_TAB_CSV = (
    '"","Current Version: 9/4 Guild Trials","","","","","","","",""\n'
    '"","Skilling Trials: https://holychikenz.github.io/SCGuildTrials/trials.html",'
    '"","","","","","","",""\n'
    '"","Combat Trials","","","","","","","",""\n'
)

HEADER_ONLY_CSV = '"Building","Hrid","Kind","Level","Guild Id","Captured At"\n'


def _row(name, hrid, kind, level, guild_id=4, at="2026-09-09T13:00:53.934Z"):
    return f'"{name}","{hrid}","{kind}","{level}","{guild_id}","{at}"'


def _csv(*rows):
    return HEADER_ONLY_CSV + "\n".join(rows) + "\n"


def test_parses_the_live_sc_block():
    """The real tab, end to end: what is built, what is a shrine, what is neither."""
    g = buildings.parse_buildings(LIVE_SC_CSV, "sc", tab="SC Buildings")

    assert g.observed is True
    assert g.captured_at == "2026-09-09T13:00:53.934Z"
    # ONE skilling building is built on SC — the Guild Observatory at level 1, worth
    # +2 Enhancing levels to every member. That single +2 is the entire behavioural
    # delta of adopting this source, so it is asserted by name rather than in bulk.
    assert g.built_skills == {"Enhancing": 1}
    assert g.skill_levels == {
        "Milking": 0, "Foraging": 0, "Woodcutting": 0, "C.Smithing": 0,
        "Crafting": 0, "Tailoring": 0, "Cooking": 0, "Brewing": 0,
        "Alchemy": 0, "Enhancing": 1,
    }
    # The guild's TRUE shrine caps, and the first direct measurement of them:
    # config.GUILD_SHRINE_CAPS holds force 4, inferred as a floor from the per-member
    # maximum on the roster tab. The tab says 5. Carried, not yet wired — the note on
    # GuildBuildings.shrine_levels says why.
    assert g.shrine_levels == {
        "force": 5, "tempo": 4, "spirit": 2, "rarity": 0, "scholar": 2,
    }
    assert g.shrine_levels["force"] > config.GUILD_SHRINE_CAPS["sc"]["force"]
    # 23 buildings, ten of them skilling.
    assert len(g.other_levels) == 13
    assert g.other_levels["/guild_buildings/dojo"] == 4
    assert g.other_levels["/guild_buildings/builders_hall"] == 6
    assert g.ignored_hrids == []


def test_empty_tab_is_unobserved_not_an_error():
    """LI, today. An empty tab is a NORMAL state and must not raise.

    The tabs are created by hand and empty ("the first write fills them",
    apps-script/README.md), so emptiness is the state every tab starts in. It is also
    distinguishable from a MISSING tab, which gviz answers with another tab's content
    (see WRONG_TAB_CSV) rather than with nothing.
    """
    for text in ("", "\n", HEADER_ONLY_CSV):
        g = buildings.parse_buildings(text, "li")
        assert g.observed is False
        assert g.skill_levels == {}
        assert g.captured_at == ""
        assert g.tab == "LI Buildings"   # filled from config when not passed


def test_unobserved_is_not_the_same_value_as_observed_zeros():
    """The distinction the `observed` flag exists for.

    Both model to the same numbers today, so nothing in the rate model separates
    them — but one is a measurement and the other is our ignorance, and a page that
    conflates them tells an officer he has data he has not got.
    """
    unobserved = buildings.parse_buildings("", "li")
    observed_zero = buildings.parse_buildings(
        _csv(_row("Guild Brewery", "/guild_buildings/brewery", "building", 0)),
        "sc",
    )
    assert unobserved.observed is False and observed_zero.observed is True
    assert unobserved.built_skills == observed_zero.built_skills == {}
    assert unobserved.captured_at == "" and observed_zero.captured_at != ""


def test_a_wrong_tab_serve_raises():
    """gviz's silent wrong-tab serve, with the payload it actually returns.

    A misspelled or deleted tab name yields the FIRST tab's content and HTTP 200. Any
    reader without this guard would emit garbage rather than fail — the regression
    scraper.py's docstring warns about in capitals.
    """
    with pytest.raises(SheetStructureError) as exc:
        buildings.parse_buildings(WRONG_TAB_CSV, "sc", tab="SC Buildings")
    assert "col 0" in str(exc.value)
    assert "gviz silently serves a different tab" in str(exc.value)


def test_a_changed_writer_header_raises():
    """The other thing the guard catches: the Apps Script writer's header moving."""
    renamed = LIVE_SC_CSV.replace('"Captured At"', '"Captured"', 1)
    with pytest.raises(SheetStructureError) as exc:
        buildings.parse_buildings(renamed, "sc", tab="SC Buildings")
    assert "col 5" in str(exc.value)


def test_a_foreign_guild_id_raises():
    """The tab holding the OTHER guild's levels: one settings typo away.

    The in-game module routes a capture to a tab through a hand-edited guild-id map.
    Wrong levels on the right tab would look entirely plausible on the page and
    mis-plan the whole week, so this raises rather than falling back — the same call
    config.shrine_caps makes for the same reason.
    """
    with pytest.raises(SheetStructureError) as exc:
        buildings.parse_buildings(LIVE_SC_CSV, "li", tab="LI Buildings")
    message = str(exc.value)
    assert "'4'" in message and "240" in message   # both ids named


def test_an_unstamped_guild_id_is_not_invented():
    """A guard with no reference is no guard: a blank id is skipped, not failed."""
    g = buildings.parse_buildings(
        _csv(_row("Guild Brewery", "/guild_buildings/brewery", "building", 3, guild_id="")),
        "sc",
    )
    assert g.skill_levels == {"Brewing": 3}


def test_levels_are_clamped_and_coerced():
    """A malformed or inflated cell cannot reach the model, by any path."""
    g = buildings.parse_buildings(
        _csv(
            _row("Guild Brewery", "/guild_buildings/brewery", "building", 999),
            _row("Guild Kitchen", "/guild_buildings/kitchen", "building", ""),
            _row("Guild Garden", "/guild_buildings/garden", "building", -3),
            _row("Guild Forge", "/guild_buildings/forge", "building", "abc"),
        ),
        "sc",
    )
    assert g.skill_levels == {
        "Brewing": config.GUILD_BUILDING_MAX_LEVEL,
        "Cooking": 0,
        "Foraging": 0,
        "C.Smithing": 0,
    }


def test_unmapped_hrids_are_kept_apart_not_dropped_silently():
    """Combat, utility and unknown buildings are carried, never modelled."""
    g = buildings.parse_buildings(
        _csv(
            _row("Guild Dojo", "/guild_buildings/dojo", "building", 4),
            _row("Guild Hall", "/guild_buildings/guild_hall", "building", 8),
            _row("Guild Zeppelin", "/guild_buildings/zeppelin", "building", 2),
            _row("Something Else", "/guild_relics/orb", "relic", 1),
        ),
        "sc",
    )
    assert g.skill_levels == {}          # nothing here grants a skilling level
    assert g.other_levels == {
        "/guild_buildings/dojo": 4,
        "/guild_buildings/guild_hall": 8,
        "/guild_buildings/zeppelin": 2,   # an hrid added after this map was written
    }
    assert g.ignored_hrids == ["/guild_relics/orb"]


def test_captured_at_is_the_oldest_row():
    """Matches roster.Provenance.captured_at, so the two provenances mean one thing."""
    g = buildings.parse_buildings(
        _csv(
            _row("Guild Brewery", "/guild_buildings/brewery", "building", 1,
                 at="2026-09-09T13:00:53.934Z"),
            _row("Guild Kitchen", "/guild_buildings/kitchen", "building", 1,
                 at="2026-09-01T08:00:00.000Z"),
        ),
        "sc",
    )
    assert g.captured_at == "2026-09-01T08:00:00.000Z"


def test_hrid_map_covers_exactly_the_ten_skilling_buildings():
    """A typo'd skill name here would silently grant nothing at all.

    BUILDING_HRID_TO_SKILL is a transcription of the prose list in config, and the
    dict is what dispatches. Pinning its values against GUILD_BUILDING_LEVELS' own
    keys is what stops the two drifting into a quiet no-op.
    """
    assert set(config.BUILDING_HRID_TO_SKILL.values()) == set(
        config.GUILD_BUILDING_LEVELS
    )
    assert len(config.BUILDING_HRID_TO_SKILL) == 10
    assert all(
        h.startswith("/guild_buildings/") for h in config.BUILDING_HRID_TO_SKILL
    )


def test_the_live_tab_names_every_hrid_the_map_expects():
    """The map is not merely self-consistent: the game still uses these hrids.

    Guards the case where an upstream rename turns a modelled building into an
    `other_levels` entry — which would look like "not built" rather than like a bug.
    """
    g = buildings.parse_buildings(LIVE_SC_CSV, "sc", tab="SC Buildings")
    assert set(g.skill_levels) == set(config.GUILD_BUILDING_LEVELS)
    assert not (set(config.BUILDING_HRID_TO_SKILL) & set(g.other_levels))


def test_to_dict_is_json_serializable_and_copies():
    import json

    g = buildings.parse_buildings(LIVE_SC_CSV, "sc", tab="SC Buildings")
    d = g.to_dict()
    json.dumps(d)                        # must not raise
    d["skill_levels"]["Enhancing"] = 99  # a copy, not the live dict
    assert g.skill_levels["Enhancing"] == 1
