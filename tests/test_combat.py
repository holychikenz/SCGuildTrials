"""The Combat Teams reader, its degrade matrix, and the flag that removes it.

Fixture-driven and OFFLINE. Nothing here touches the network: ``_fetch_combat``'s
tests monkeypatch ``combat.scrape_combat_tab``, and every CSV below is a literal.

The subject is not really the parser — it is the PROMISE that combat data can never
stop a deploy. SC is ``required=True``, so an uncaught raise anywhere on this path
takes down every page of BOTH guilds; that happened on 2026-07-25 over a required
parse failure (``config.py``'s incident note) and combat teams are a second-order
input that must never be able to do it again. So the plan's §5 degraded matrix is
enumerated here row by row: each failure mode must come back as ``available: false``
with a NON-EMPTY human reason, print one ``WARNING`` line, and let the build ship.

WRONG_TAB_CSV is the load-bearing fixture. As of 2026-09-09 the two tabs DO NOT
EXIST on the sheet — Layer 1's manual deploy has not been done — and gviz does not
error on a name it cannot find: it silently serves the spreadsheet's FIRST tab. The
bytes below are what a live build actually gets today when it asks for
``SC Combat Teams``: 3518 bytes of the officers' hand-maintained "Trial Assignments"
prose, captured verbatim. "The tab does not exist" is therefore not a state anything
can detect by size or emptiness — only the header guard can tell, which is why
``config.COMBAT_SENTINEL_HEADERS`` is equals-throughout on all seven cells.

SEVEN-WIDE AND NINE-WIDE TABS ARE BOTH TESTED, and that is not thoroughness — it is
the contract. The reader shipped BEFORE the writer that appended the two loadout
columns, so "seven wide" is the live state on the day this lands and "nine wide" is
the state a week later; a rollback of the writer returns to seven. Every pairing has
to parse, or the cross-repo rollout has an ordering it cannot survive.
"""

import copy
import csv
import io
import json

import pytest

from src import build, combat, config, processor, trials
from src.reader import MemberRow, SheetStructureError, SkillEntry

AT = "2026-09-09T18:22:41.507Z"

HEADER_ONLY_CSV = (
    '"Member","Trial Hrid","Team","Role","Slot","Guild Id","Generated At"\n'
)

# Five seats over two teams, in the order the writer sorts them (Team then Slot) —
# so `teams` comes back in first-seen order and party_size is 3 then 2.
LIVE_SHAPE_CSV = HEADER_ONLY_CSV + (
    f'"Yedic","/guild_combat/chameleon","SC Team 1","tank","tank 1","4","{AT}"\n'
    f'"Pipsqueak","/guild_combat/chameleon","SC Team 1","cursed","cursed 1","4","{AT}"\n'
    f'"jodend","/guild_combat/chameleon","SC Team 1","healer_blooming",'
    f'"healer_blooming 1","4","{AT}"\n'
    f'"IronOwl","/guild_combat/hedgehog","SC Team 2","tank","tank 1","4","{AT}"\n'
    f'"Maine","/guild_combat/hedgehog","SC Team 2","cursed","cursed 1","4","{AT}"\n'
)

# What gviz serves TODAY for "SC Combat Teams", which does not exist: the first tab.
# Captured live 2026-09-09 (3518 bytes total; the first six rows are enough — the
# guard reads row 0, and the point is that row 0 is plausible prose, not an error).
WRONG_TAB_CSV = (
    '"","Current Version: 9/4 Guild Trials","","","","","","","","","","","","","",'
    '"","","",""\n'
    '"","Skilling Trials: https://holychikenz.github.io/SCGuildTrials/trials.html",'
    '"","","","","","","","","","","","","","","","",""\n'
    '"","Combat Trials","","","","","","","","","","","","","","","","",""\n'
    '"","","","","","Survey Corps","","Lactose Intolerance","","","","","","",'
    '"Priority","","","",""\n'
    '"","Trial 1","","Badger","","Team 1","","Team 1","","",'
    '"Mages > Melee / No Ranged","","","","Magic","","","",""\n'
    '"","Trial 2","","Swarm","","Team 2","","Team 2","","",'
    '"Melee/Ranged / Mages should join Badger first","","","","Melee/Ranged","","",'
    '"",""\n'
)

# This guild's own sign-up tab header, captured live 2026-09-09. Columns F-G (0-based
# 5..6) are the week's two bosses; both guilds' tabs carry the same pair today.
LIVE_SIGNUP_HEADER = (
    '"User","Milking","Alchemy","Crafting","Enhancing","Swarm","Badger"\n'
    '"Adelaine","FALSE","FALSE","TRUE","FALSE","FALSE","TRUE"\n'
)


def _row(name, hrid, team, role, slot, guild_id=4, at=AT):
    return f'"{name}","{hrid}","{team}","{role}","{slot}","{guild_id}","{at}"'


def _csv(*rows):
    return HEADER_ONLY_CSV + "\n".join(rows) + "\n"


def _observation(hrid_a="/guild_combat/swarm", hrid_b="/guild_combat/badger"):
    """A minimal usable observation, for the _fetch_combat and _write_guild tests."""
    return combat.parse_combat(
        _csv(
            _row("Yedic", hrid_a, "SC Team 1", "tank", "tank 1"),
            _row("IronOwl", hrid_b, "SC Team 2", "cursed", "cursed 1"),
        ),
        "sc",
        tab="SC Combat Teams",
    )


# --- The parser -------------------------------------------------------------------


def test_parses_a_machine_written_tab():
    """Five rows, two teams, and the trials.json shape of each one."""
    g = combat.parse_combat(LIVE_SHAPE_CSV, "sc", tab="SC Combat Teams")

    assert g.observed is True
    assert g.tab == "SC Combat Teams"
    assert g.guild_key == "sc"
    # min() across the stamps, as buildings.captured_at does: one publish stamps
    # every row identically, so this differs from the newest only on a torn write.
    assert g.generated_at == AT
    assert g.hrids == {"/guild_combat/chameleon", "/guild_combat/hedgehog"}
    # A SEVEN-wide tab — what the older writer publishes — still parses, and every
    # seat simply carries no loadout. This is the backwards-compatibility lever the
    # whole cross-repo rollout hangs on, so it is asserted on the main fixture rather
    # than off in a corner.
    assert g.loadouts == {}

    # TAB ORDER: first-seen (hrid, team) walking rows top to bottom.
    assert [t.team for t in g.teams] == ["SC Team 1", "SC Team 2"]
    assert [len(t.roster) for t in g.teams] == [3, 2]

    first = g.teams[0].to_dict()
    assert first == {
        "hrid": "/guild_combat/chameleon",
        "team": "SC Team 1",
        "party_size": 3,
        "roster": [
            {"name": "Yedic", "role": "tank", "slot": "tank 1",
             "loadout_id": "", "loadout_name": ""},
            {"name": "Pipsqueak", "role": "cursed", "slot": "cursed 1",
             "loadout_id": "", "loadout_name": ""},
            {"name": "jodend", "role": "healer_blooming", "slot": "healer_blooming 1",
             "loadout_id": "", "loadout_name": ""},
        ],
    }
    # party_size is derived, never carried: it cannot disagree with the roster.
    assert all(t["party_size"] == len(t["roster"]) for t in g.to_dict()["teams"])
    # NO characterId reaches the artefact, by construction on the writer's side.
    assert "characterId" not in json.dumps(g.to_dict())
    assert "character_id" not in json.dumps(g.to_dict())


@pytest.mark.parametrize(
    "csv_text",
    ["", "\n", "   \n", HEADER_ONLY_CSV],
    ids=["empty", "newline", "spaces", "header-only"],
)
def test_empty_tab_is_unobserved_not_an_error(csv_text):
    """§5 row 3: the tab exists, the optimiser has never published to it.

    NOT an error, and deliberately NOT detected by byte count — a MISSING tab serves
    another tab's content (see WRONG_TAB_CSV), so emptiness here really is emptiness.
    """
    g = combat.parse_combat(csv_text, "sc")

    assert g.observed is False
    assert g.tab == "SC Combat Teams"  # filled from config when not passed
    assert g.generated_at == ""
    assert g.teams == []
    assert g.hrids == set()


def test_a_wrong_tab_serve_raises():
    """§5 row 2, and the reason this whole guard exists.

    The two tabs do not exist yet, and gviz answers for a name it cannot find with
    the FIRST tab's content — real prose, 3518 bytes, HTTP 200. Nothing but an
    equals-on-every-cell header guard can tell that from a real tab.
    """
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(WRONG_TAB_CSV, "sc", tab="SC Combat Teams")

    msg = str(exc.value)
    assert "col 0: expected equals 'Member'" in msg
    assert "Current Version" in msg  # what it actually got, quoted back
    assert "MAY NOT EXIST" in msg    # and the remedy: create the tab by that name
    # Every one of the seven cells is checked, so the whole payload is named at once
    # rather than one cell per build.
    assert msg.count("col ") == 7


def test_a_changed_writer_header_raises():
    """One renamed cell — the optimiser's HEADER drifting from config's — is refused."""
    drifted = LIVE_SHAPE_CSV.replace('"Trial Hrid"', '"Trial"', 1)

    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(drifted, "sc", tab="SC Combat Teams")

    msg = str(exc.value)
    assert "col 1: expected equals 'Trial Hrid', got 'Trial'" in msg
    assert "combatTab.js" in msg  # where the other half of the contract lives


def test_another_guilds_id_raises():
    """§5 row 4: LI's teams on SC's tab would glow the wrong tiles, plausibly."""
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(
            _csv(_row("Yedic", "/guild_combat/swarm", "LI Team 1", "tank", "tank 1", 240)),
            "sc",
            tab="SC Combat Teams",
        )

    msg = str(exc.value)
    assert "guild id '240'" in msg and "guild id 4" in msg
    assert "ANOTHER GUILD'S" in msg
    # An UNSTAMPED row is not invented against: a guard with no reference is no guard.
    ok = combat.parse_combat(
        _csv(_row("Yedic", "/guild_combat/swarm", "SC Team 1", "tank", "tank 1", "")),
        "sc",
        tab="SC Combat Teams",
    )
    assert ok.observed is True


def test_a_non_combat_hrid_raises():
    """§5 row 4: a skilling hrid in Trial Hrid keys no combat tile at all."""
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(
            _csv(
                _row(
                    "Yedic", "/guild_skilling/milking", "SC Team 1", "tank", "tank 1"
                )
            ),
            "sc",
            tab="SC Combat Teams",
        )

    assert "/guild_skilling/milking" in str(exc.value)
    assert "not a combat trial" in str(exc.value)


def test_a_blank_member_name_raises():
    """On a MACHINE tab a blank name is a broken write, not the end of the table.

    The hand-maintained tabs end at the first blank name (``reader.parse``,
    ``signup.parse_signup``). This one is cleared and rewritten from A1 with no blank
    rows, so the same convention here would silently drop half a party — or glow
    somebody else's tile if the blank were mid-party.
    """
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(
            _csv(
                _row("Yedic", "/guild_combat/swarm", "SC Team 1", "tank", "tank 1"),
                _row("", "/guild_combat/swarm", "SC Team 1", "cursed", "cursed 1"),
            ),
            "sc",
            tab="SC Combat Teams",
        )

    assert "blank Member on row 3" in str(exc.value)


# --- The optional loadout pair: a nine-wide tab ------------------------------------
#
# The writer appended `Loadout Id` and `Loadout` at indices 7 and 8 on 2026-09-15.
# Everything below is about the two properties that make that safe: the reader accepts
# BOTH widths, and the `Loadout` cell — the first in this pipeline ever to contain a
# comma or a double quote — survives a REAL CSV round trip rather than a hand-written
# approximation of one.

NINE_HEADER = [
    "Member", "Trial Hrid", "Team", "Role", "Slot", "Guild Id", "Generated At",
    "Loadout Id", "Loadout",
]

# A genuine recommendation, with everything the shape has to survive: a `null` slot
# (wear nothing there, which is NOT the same as omitting the slot), an EMPTY trigger
# list (no conditions at all, which is NOT "the game's defaults"), and a populated one.
LOADOUT = {
    "equipment": {
        "/equipment_types/two_hand": {"hrid": "/items/griffin_bulwark_refined"},
        "/equipment_types/off_hand": None,
        "/equipment_types/head": {"hrid": "/items/corsair_helmet_refined"},
    },
    "abilities": [
        {"hrid": "/abilities/invincible", "triggers": []},
        {"hrid": "/abilities/provoke", "triggers": []},
        {
            "hrid": "/abilities/taunt",
            "triggers": [
                {
                    "dependencyHrid": "/ability_trigger_dependencies/self",
                    "conditionHrid": "/ability_trigger_conditions/mp",
                    "comparatorHrid": "/ability_trigger_comparators/less_than_equal",
                    "value": 50,
                }
            ],
        },
    ],
}
LOADOUT_JSON = json.dumps(LOADOUT, sort_keys=True, separators=(",", ":"))
LOADOUT_ID = "ld_9c41ab27f0e3"

OTHER_LOADOUT = {"equipment": {}, "abilities": [None, {"hrid": "/abilities/puncture",
                                                       "triggers": []}]}
OTHER_JSON = json.dumps(OTHER_LOADOUT, sort_keys=True, separators=(",", ":"))
OTHER_ID = "ld_00ff11ee22dd"


def _csv9(*rows, header=None):
    """Serialise through the REAL csv module — not an f-string.

    This is the point of R4. A `Loadout` cell is canonical JSON: commas throughout and
    a double quote around every key. gviz wraps such a field in double quotes and
    DOUBLES each internal one (RFC 4180), and `csv.reader` is what undoes it. Building
    the fixture with `csv.writer` means the bytes under test are quoted and doubled the
    way the wire really does it, so the test exercises the seam instead of agreeing
    with itself.
    """
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(header or NINE_HEADER)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def _row9(name, team="SC Team 1", slot="tank 1", ld_id=LOADOUT_ID, blob=LOADOUT_JSON):
    return [name, "/guild_combat/swarm", team, "tank", slot, "4", AT, ld_id, blob]


# -----------------------------------------------------------------------------
# TEN WIDE — the curated loadout NAME, appended 2026-09-18
# -----------------------------------------------------------------------------
# The reader must now accept SEVEN, NINE and TEN, and it must go on accepting nine
# while col 9 is declared in COMBAT_OPTIONAL_HEADERS — that is the trap this block
# exists for, because declaring the tenth cell without a presence guard would refuse
# the nine-wide tab that is LIVE, on the first repository in the ship order. Eight
# and eleven are refused on purpose: eight is not an old writer but a torn one.

TEN_HEADER = NINE_HEADER + ["Loadout Name"]

# A value with a space and parentheses, through real CSV, because that is what the
# curated names actually look like. `dps_fire` is "Fire DPS (Blazing)": no titlecasing
# of `role` produces it, which is the whole reason the name travels rather than being
# reconstructed on this side.
LOADOUT_NAME = "Fire DPS (Blazing)"


def _csv10(*rows, header=None):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(header or TEN_HEADER)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def _row10(name, team="SC Team 1", slot="tank 1", ld_id=LOADOUT_ID,
           blob=LOADOUT_JSON, lname=LOADOUT_NAME):
    return _row9(name, team=team, slot=slot, ld_id=ld_id, blob=blob) + [lname]


def test_a_seven_wide_tab_carries_neither_id_nor_name():
    """The oldest supported width. Both optional halves degrade to "", not to a guess."""
    g = combat.parse_combat(LIVE_SHAPE_CSV, "sc", tab="SC Combat Teams")
    seats = [s for t in g.teams for s in t.roster]
    assert seats, "the fixture must actually have seats"
    assert all(s.loadout_id == "" for s in seats)
    assert all(s.loadout_name == "" for s in seats)


def test_a_nine_wide_tab_still_parses_once_col_nine_is_declared():
    """THE regression this whole change is shaped around.

    COMBAT_OPTIONAL_HEADERS now declares col 9, and `_cell` returns "" for a column a
    row does not have — so a validator that checked every declared entry regardless of
    width would refuse today's live tab with "col 9: expected equals 'Loadout Name',
    got ''". The presence guard is what makes nine a narrower SUPPORTED width rather
    than a mismatch.
    """
    assert 9 in config.COMBAT_OPTIONAL_HEADERS, "or this test is asserting nothing"
    g = combat.parse_combat(
        _csv9(_row9("Yedic"), _row9("IronOwl", slot="tank 2")),
        "sc",
        tab="SC Combat Teams",
    )
    assert g.observed is True
    assert [s.loadout_id for s in g.teams[0].roster] == [LOADOUT_ID, LOADOUT_ID]
    assert [s.loadout_name for s in g.teams[0].roster] == ["", ""]
    assert set(g.loadouts) == {LOADOUT_ID}


def test_a_ten_wide_tab_carries_the_curated_name():
    """A space and parentheses, through the real csv module."""
    g = combat.parse_combat(
        _csv10(_row10("Yedic"), _row10("IronOwl", slot="tank 2", lname="Cursed")),
        "sc",
        tab="SC Combat Teams",
    )
    assert [s.loadout_name for s in g.teams[0].roster] == [LOADOUT_NAME, "Cursed"]
    # On the SEAT and not in `loadouts` — two seats sharing one id may rightfully
    # carry two names, and putting the name in the blob would make that a conflict.
    assert set(g.loadouts) == {LOADOUT_ID}
    assert "loadout_name" not in json.dumps(g.loadouts)
    assert g.to_dict()["teams"][0]["roster"][0]["loadout_name"] == LOADOUT_NAME


def test_two_seats_on_one_loadout_may_carry_different_names():
    """The §2.2 case, on the reader's side: one id, two rightful labels, no error."""
    g = combat.parse_combat(
        _csv10(_row10("Yedic", lname="Fire DPS (Blazing)"),
               _row10("IronOwl", slot="tank 2", lname="Nature DPS")),
        "sc",
        tab="SC Combat Teams",
    )
    assert set(g.loadouts) == {LOADOUT_ID}
    assert [s.loadout_name for s in g.teams[0].roster] == [
        "Fire DPS (Blazing)", "Nature DPS"
    ]


def test_a_blank_name_on_a_seated_loadout_is_not_an_error():
    """"" is the only degradation, and it is never guessed at from `role`."""
    g = combat.parse_combat(
        _csv10(_row10("Yedic", lname="")), "sc", tab="SC Combat Teams"
    )
    seat = g.teams[0].roster[0]
    assert seat.loadout_name == ""
    assert seat.loadout_id == LOADOUT_ID, "the loadout was lost with the label"
    assert seat.role == "tank", "the role must not have been borrowed as a name"


def test_a_blank_name_and_a_blank_pair_is_a_bare_seat():
    """The seat still publishes. The three optional cells degrade together."""
    g = combat.parse_combat(
        _csv10(_row10("Yedic", ld_id="", blob="", lname="")),
        "sc",
        tab="SC Combat Teams",
    )
    seat = g.teams[0].roster[0]
    assert (seat.loadout_id, seat.loadout_name) == ("", "")
    assert g.loadouts == {}


def test_an_eight_wide_tab_is_refused_by_the_allow_list():
    """Not an old writer — a TORN one: a Loadout Id with no JSON beside it.

    This is why the width is an allow-list and not a maximum. Skipping absent optional
    columns alone would accept eight quite happily, and then attribute a loadout to a
    column that was never written.
    """
    eight = NINE_HEADER[:8]
    rows = [_row9("Yedic")[:8]]
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(eight)
    for r in rows:
        w.writerow(r)
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(buf.getvalue(), "sc", tab="SC Combat Teams")
    msg = str(exc.value)
    assert "header is 8 cells wide" in msg
    assert str(config.COMBAT_ACCEPTED_WIDTHS) in msg


def test_an_eleven_wide_tab_is_refused_by_the_allow_list():
    """A column nobody on this side knows about. Refused, not ignored."""
    eleven = TEN_HEADER + ["Something New"]
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(
            _csv10(_row10("Yedic") + ["x"], header=eleven),
            "sc",
            tab="SC Combat Teams",
        )
    assert "header is 11 cells wide" in str(exc.value)


def test_a_mistyped_tenth_header_raises_naming_col_nine():
    """Ten wide with a drifted tenth cell is a broken writer, not an old one."""
    bad = list(TEN_HEADER)
    bad[9] = "Loadout name"  # lowercase n — the exact drift a human would introduce
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(
            _csv10(_row10("Yedic"), header=bad), "sc", tab="SC Combat Teams"
        )
    assert "col 9: expected equals 'Loadout Name', got 'Loadout name'" in str(exc.value)



def test_a_nine_wide_tab_parses_and_dedupes():
    """The feature: seats point at ids, and the loadouts live once each."""
    text = _csv9(
        _row9("Yedic"),
        _row9("IronOwl", slot="tank 2"),
        _row9("Maine", slot="tank 3", ld_id=OTHER_ID, blob=OTHER_JSON),
    )
    g = combat.parse_combat(text, "sc", tab="SC Combat Teams")

    assert g.observed is True
    assert [s.loadout_id for s in g.teams[0].roster] == [
        LOADOUT_ID, LOADOUT_ID, OTHER_ID
    ]
    # Denormalised on the tab, normalised here: three rows, two loadouts.
    assert set(g.loadouts) == {LOADOUT_ID, OTHER_ID}
    assert g.loadouts[LOADOUT_ID] == LOADOUT

    # `triggers: []` means NO CONDITIONS, not "the game's defaults", so an empty list
    # must arrive as an empty list and not as a missing key or a null.
    abilities = g.loadouts[LOADOUT_ID]["abilities"]
    assert abilities[0]["triggers"] == []
    assert abilities[2]["triggers"][0]["value"] == 50
    # Abilities are POSITIONAL: index 0 is the special, 1..4 the rotation. A `null`
    # entry is a real position and must not be filtered away.
    assert g.loadouts[OTHER_ID]["abilities"][0] is None
    # A `null` equipment slot means "wear nothing here" and is likewise not a gap.
    assert g.loadouts[LOADOUT_ID]["equipment"]["/equipment_types/off_hand"] is None
    # The engine spelling, published literally. `itemHrid` is the UI's and converting
    # between them is SCLIRoster's exportRoster.js's job, not this reader's.
    assert "itemHrid" not in json.dumps(g.to_dict())
    assert g.to_dict()["teams"][0]["roster"][0]["loadout_id"] == LOADOUT_ID


def test_the_loadout_cell_survives_a_real_csv_round_trip():
    """R4, directly: the first cell in this pipeline to hold commas and quotes.

    The blob below is quoted and doubled by `csv.writer` exactly as gviz does it — the
    raw text really does contain `""` sequences — and comes back byte-identical. A
    reader that split rows on commas by hand would shear it at the first one and hand
    the fragments to `Guild Id` and `Generated At`.
    """
    text = _csv9(_row9("Yedic"))

    assert '""' in text, "the fixture must actually be doubled, or it tests nothing"
    assert text.count(",") > 20, "and must actually contain commas inside the cell"

    g = combat.parse_combat(text, "sc", tab="SC Combat Teams")
    assert g.loadouts[LOADOUT_ID] == LOADOUT
    # And byte-for-byte, not merely equal-as-objects: the canonical JSON is what the
    # id is derived from, so a re-serialisation that differs would break the dedupe.
    assert json.dumps(
        g.loadouts[LOADOUT_ID], sort_keys=True, separators=(",", ":")
    ) == LOADOUT_JSON


def test_a_blank_loadout_pair_is_a_seat_without_a_recommendation():
    """A member the optimiser could not build for still gets a seat."""
    g = combat.parse_combat(
        _csv9(_row9("Yedic", ld_id="", blob=""), _row9("IronOwl", slot="tank 2")),
        "sc",
        tab="SC Combat Teams",
    )
    assert [s.loadout_id for s in g.teams[0].roster] == ["", LOADOUT_ID]
    assert set(g.loadouts) == {LOADOUT_ID}


def test_a_half_filled_loadout_pair_raises():
    """Both cells or neither; one alone is a torn write."""
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(
            _csv9(_row9("Yedic", blob="")), "sc", tab="SC Combat Teams"
        )
    assert "half-filled loadout on row 2" in str(exc.value)

    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(
            _csv9(_row9("Yedic", ld_id="")), "sc", tab="SC Combat Teams"
        )
    assert "half-filled loadout on row 2" in str(exc.value)


def test_malformed_loadout_json_raises():
    """Not a crash, not a silent drop: a named SheetStructureError, which degrades."""
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(
            _csv9(_row9("Yedic", blob='{"equipment":{,}')),
            "sc",
            tab="SC Combat Teams",
        )
    assert "not valid JSON" in str(exc.value)
    assert "row 2" in str(exc.value)

    # A well-formed blob of the WRONG TYPE is refused too — a list would reach the
    # userscript as a shape it cannot read.
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(
            _csv9(_row9("Yedic", blob="[1,2,3]")), "sc", tab="SC Combat Teams"
        )
    assert "not an object" in str(exc.value)


def test_one_id_with_two_different_blobs_raises():
    """The id is CONTENT-derived, so this cannot be two legitimate publishes.

    The reader does not recompute the hash — that rule lives in exactly one file, on
    the writer's side. It verifies instead, and this is the property it can verify
    without owning the rule.
    """
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(
            _csv9(
                _row9("Yedic"),
                _row9("IronOwl", slot="tank 2", blob=OTHER_JSON),
            ),
            "sc",
            tab="SC Combat Teams",
        )
    msg = str(exc.value)
    assert "DIFFERENT JSON" in msg and LOADOUT_ID in msg

    # The SAME id with the SAME JSON is the normal case — every member sharing a
    # template hits it — and must not raise.
    ok = combat.parse_combat(
        _csv9(_row9("Yedic"), _row9("IronOwl", slot="tank 2")),
        "sc",
        tab="SC Combat Teams",
    )
    assert set(ok.loadouts) == {LOADOUT_ID}


def test_a_mistyped_optional_header_on_a_wide_tab_raises():
    """Nine wide with a drifted eighth cell is a broken writer, not an old one.

    Guessing which would attribute JSON to whatever column happened to hold it.
    """
    bad = list(NINE_HEADER)
    bad[7] = "Loadout ID"  # capital D — the exact drift a human would introduce
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(
            _csv9(_row9("Yedic"), header=bad), "sc", tab="SC Combat Teams"
        )
    msg = str(exc.value)
    assert "col 7: expected equals 'Loadout Id', got 'Loadout ID'" in msg


def test_the_optional_pair_is_not_required_on_a_seven_wide_tab():
    """The lever, stated as its own test: seven cells validate, unchanged.

    The reader ships BEFORE the writer, and a rollback of the writer returns the tab
    to seven. Neither direction may raise.
    """
    g = combat.parse_combat(LIVE_SHAPE_CSV, "sc", tab="SC Combat Teams")
    assert g.observed is True
    assert g.loadouts == {}
    assert all(s.loadout_id == "" for t in g.teams for s in t.roster)


def test_a_wrong_tab_serve_still_names_exactly_the_seven_required_cells():
    """The wrong-tab fixture is NINETEEN columns wide, which is the trap here.

    A width-triggered check of the optional pair would add two more mismatches to a
    message whose one job is to say "this is not the combat tab". The optional pair is
    therefore checked only once the required seven have all passed.
    """
    with pytest.raises(SheetStructureError) as exc:
        combat.parse_combat(WRONG_TAB_CSV, "sc", tab="SC Combat Teams")
    assert str(exc.value).count("col ") == 7


# --- The cross-check ---------------------------------------------------------------


def test_signup_combat_pair_reads_cells_five_and_six():
    """Columns F-G by POSITION, the geometry signup.py and draw.py already read by."""
    assert combat.COMBAT_PAIR_COL_START == 5
    assert combat.signup_combat_pair(LIVE_SIGNUP_HEADER, "SC Trial Signup") == [
        "Swarm",
        "Badger",
    ]

    # §5 row 7: the tab is not in tick-box sign-up format at all.
    with pytest.raises(SheetStructureError) as exc:
        combat.signup_combat_pair(WRONG_TAB_CSV, "SC Trial Signup")
    assert "expected column 0 to contain 'User'" in str(exc.value)

    # A FIVE-cell header (the skilling block, no bosses) is too short, not blank.
    with pytest.raises(SheetStructureError) as exc:
        combat.signup_combat_pair(
            '"User","Milking","Alchemy","Crafting","Enhancing"\n', "SC Trial Signup"
        )
    assert "too few columns" in str(exc.value)

    # A blank F or G is a rebuilt tab, not an unnamed boss.
    with pytest.raises(SheetStructureError) as exc:
        combat.signup_combat_pair(
            '"User","Milking","Alchemy","Crafting","Enhancing","","Badger"\n',
            "SC Trial Signup",
        )
    assert "blank combat-boss header in column(s) 5" in str(exc.value)

    # "" — the sign-up fetch itself failed structurally — is refused, not tolerated.
    with pytest.raises(SheetStructureError):
        combat.signup_combat_pair("", "SC Trial Signup")


def test_cross_check_is_order_case_and_form_insensitive():
    """A SET of bosses, never a date. Order, case and hrid-vs-label all fold away."""
    assert combat.norm_trial("/guild_combat/swarm") == "swarm"
    assert combat.norm_trial("Swarm") == "swarm"

    obs = _observation()  # swarm + badger
    assert combat.cross_check(obs, ["Badger", "Swarm"]) == ""
    assert combat.cross_check(obs, ["swarm", "badger"]) == ""

    # §5 rows 5 and 6: whichever side is stale, BOTH sets are named and neither is
    # blamed — the two writers refresh on their own schedules.
    reason = combat.cross_check(obs, ["Chameleon", "Hedgehog"])
    assert "stale" in reason
    assert "[badger, swarm]" in reason
    assert "[chameleon, hedgehog]" in reason
    assert "does not guess which" in reason


# --- _fetch_combat: the whole degrade matrix ---------------------------------------


def _degrade(monkeypatch, capsys, result):
    """Run _fetch_combat with scrape_combat_tab replaced by ``result``."""

    def fake(tab_name, guild_key):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(combat, "scrape_combat_tab", fake)
    out = build._fetch_combat(build.GUILD_SITES[0], LIVE_SIGNUP_HEADER)
    return out, capsys.readouterr().err


def test_fetch_combat_degrades_on_every_non_network_failure(monkeypatch, capsys):
    """R7, and the promise: no sheet content can stop the deploy.

    Every row of §5 that the build decides, in one place, with the one thing they all
    have in common asserted for each: a non-empty reason and exactly one WARNING.
    """
    # (a) unreadable — the tab is missing, hand-edited, or the header drifted.
    (obs, reason), err = _degrade(
        monkeypatch, capsys, SheetStructureError("header did not match")
    )
    assert obs is None
    assert "could not be read" in reason and "header did not match" in reason

    # (b) never written — a statement, not a failure.
    (obs, reason), err_b = _degrade(
        monkeypatch,
        capsys,
        combat.GuildCombat(tab="SC Combat Teams", guild_key="sc", observed=False),
    )
    assert obs is not None and obs.observed is False
    assert "has never been written" in reason
    assert "report --publish-combat" in reason

    # (c) stale against the sign-up header (the tab says chameleon/hedgehog, the
    #     sheet says swarm/badger). The observation is CARRIED, the block withheld.
    (obs, reason), err_c = _degrade(
        monkeypatch,
        capsys,
        _observation("/guild_combat/chameleon", "/guild_combat/hedgehog"),
    )
    assert obs is not None and obs.observed is True
    assert "stale" in reason and "swarm" in reason and "chameleon" in reason

    # (d) the sign-up header itself is unreadable -> cannot cross-check (§5 row 7).
    monkeypatch.setattr(combat, "scrape_combat_tab", lambda t, k: _observation())
    obs, reason = build._fetch_combat(build.GUILD_SITES[0], WRONG_TAB_CSV)
    err_d = capsys.readouterr().err
    assert obs is not None
    assert "Cannot cross-check" in reason

    # (e) all well -> no reason, and NO warning.
    monkeypatch.setattr(combat, "scrape_combat_tab", lambda t, k: _observation())
    obs, reason = build._fetch_combat(build.GUILD_SITES[0], LIVE_SIGNUP_HEADER)
    err_e = capsys.readouterr().err
    assert obs is not None and obs.observed is True
    assert reason == ""
    assert err_e == ""

    for label, err in (("a", err), ("b", err_b), ("c", err_c), ("d", err_d)):
        assert err.count("WARNING (sc): combat teams unavailable — ") == 1, label


def test_fetch_combat_lets_a_network_error_propagate(monkeypatch):
    """A RuntimeError is NOT swallowed, by the same rule as every other tab.

    ``build.py``'s roster and buildings blocks both let one through: the same host
    serves the member tab, which would have failed first, so there is no page to ship
    either way. Catching it here would turn a dead sheet into a silently combat-less
    site, and the deploy is meant to be loud about that.
    """

    def boom(tab_name, guild_key):
        raise RuntimeError("Failed to reach Google Sheets gviz endpoint: timeout")

    monkeypatch.setattr(combat, "scrape_combat_tab", boom)
    with pytest.raises(RuntimeError):
        build._fetch_combat(build.GUILD_SITES[0], LIVE_SIGNUP_HEADER)


def test_flag_off_skips_the_fetch_entirely(monkeypatch, capsys):
    """§5 row 1: gated at the FETCH, so the rollback covers a broken writer too."""
    calls = []
    monkeypatch.setattr(
        combat, "scrape_combat_tab", lambda t, k: calls.append(t) or _observation()
    )
    monkeypatch.setattr(config, "COMBAT_SOURCE_ENABLED", False)

    obs, reason = build._fetch_combat(build.GUILD_SITES[0], LIVE_SIGNUP_HEADER)

    assert calls == [], "the flag must be checked BEFORE the network, not after"
    assert obs is None
    assert "COMBAT_SOURCE_ENABLED is off" in reason
    assert "combat teams unavailable" in capsys.readouterr().err


# --- The artefact ------------------------------------------------------------------

SKILLS = ["Foraging", "Brewing"]


def _member(name, level=100):
    return MemberRow(
        name=name,
        main_classes="",
        flex="",
        flex_levels=[],
        skills={
            s: SkillEntry(level=level, tool=False, top=False, bot=False, house=4)
            for s in config.SKILLS
        },
    )


def _ten():
    return [_member(f"m{i}", 90 + i) for i in range(10)]


def _week(members, cap=4):
    return trials.run_week(
        members, skills=list(SKILLS), seed=7, cap=cap, strategy="random"
    ).to_dict()


def _inputs(site, members, register, combat_obs=None, combat_reason=""):
    return build._GuildInputs(
        site_key=site.key,
        members=members,
        register=register,
        picks=None,
        signup_unavailable="not in this test",
        signup_unavailable_short="test",
        combat=combat_obs,
        combat_unavailable=combat_reason,
    )


def _draw():
    return build.draw_model.TrialDraw(skills=list(SKILLS), date="")


def test_write_guild_attaches_the_block_on_both_guilds(tmp_path, monkeypatch):
    """§4.2, published: five keys, always the same five, and the CI line says so."""
    monkeypatch.setattr(build, "OUTPUT_DIR", tmp_path)
    members = _ten()

    for site in build.GUILD_SITES:
        register = processor.process(members)
        obs = _observation()
        summary = build._write_guild(
            site, _inputs(site, members, register, obs), _week(members), None, _draw(), ""
        )
        published = json.loads(
            (site.out_dir / build.TRIALS_JSON).read_text(encoding="utf-8")
        )
        block = published["combat"]

        assert set(block) == {
            "available",
            "unavailable",
            "source",
            "generated_at",
            "loadout_schema",
            "loadouts",
            "trials",
        }
        assert block["loadout_schema"] == 1
        assert block["loadouts"] == {"shape": "engine-dto", "by_id": {}}
        assert block["available"] is True
        assert block["unavailable"] == ""
        assert block["source"] == site.combat_tab
        assert block["generated_at"] == AT
        assert [t["hrid"] for t in block["trials"]] == [
            "/guild_combat/swarm",
            "/guild_combat/badger",
        ]
        assert all(t["party_size"] == len(t["roster"]) for t in block["trials"])
        assert all(
            set(r) == {"name", "role", "slot", "loadout_id", "loadout_name"}
            for t in block["trials"]
            for r in t["roster"]
        )
        # Seven-wide fixture: the seats publish, with no loadout to point at.
        assert all(
            r["loadout_id"] == "" for t in block["trials"] for r in t["roster"]
        )
        assert "combat 2026-09-09 swarmx1, badgerx1" in summary

        # And unavailable: no observation at all, with no reason recorded — the
        # hand-built-inputs case — still answers in words rather than a bare False.
        register = processor.process(members)
        summary = build._write_guild(
            site, _inputs(site, members, register), _week(members), None, _draw(), ""
        )
        block = json.loads(
            (site.out_dir / build.TRIALS_JSON).read_text(encoding="utf-8")
        )["combat"]
        assert block["available"] is False
        assert block["unavailable"] == f"The {site.combat_tab!r} tab was not read."
        assert block["trials"] == [] and block["generated_at"] == ""
        # The two loadout keys are present on the UNAVAILABLE path too: a consumer
        # never has to ask whether the key exists before asking whether it is
        # populated.
        assert block["loadout_schema"] == 1
        assert block["loadouts"] == {"shape": "engine-dto", "by_id": {}}
        assert "combat NONE — " in summary


def test_flag_off_is_byte_identical_and_on_is_additive(tmp_path, monkeypatch):
    """The rollback, pinned: False removes the key and changes nothing else.

    Modelled on test_register_week.py's flag test. `generated_at` and `week_date` are
    popped before the comparison for the reason test_roster.py:388-389 pops them —
    they are wall-clock, not a product of the change under test.
    """
    monkeypatch.setattr(build, "OUTPUT_DIR", tmp_path)
    site = build.GUILD_SITES[0]
    members = _ten()

    def run():
        register = processor.process(members)
        build._write_guild(
            site,
            _inputs(site, members, register, _observation()),
            _week(members),
            None,
            _draw(),
            "",
        )
        text = (tmp_path / build.TRIALS_JSON).read_text(encoding="utf-8")
        return json.loads(text), text

    monkeypatch.setattr(config, "COMBAT_SOURCE_ENABLED", False)
    off, off_text = run()
    monkeypatch.setattr(config, "COMBAT_SOURCE_ENABLED", True)
    on, on_text = run()

    assert "combat" not in off
    assert set(on) - set(off) == {"combat"}

    off_cmp, on_cmp = copy.deepcopy(off), copy.deepcopy(on)
    for d in (off_cmp, on_cmp):
        d.pop("generated_at", None)
        d.pop("week_date", None)
    on_cmp.pop("combat")
    assert on_cmp == off_cmp

    # BYTES, not just equal dicts: the claim is that False leaves trials.json
    # byte-identical, and dict equality is order-blind while the file is not. The key
    # is appended LAST (after provenance), so deleting it from the flag-on document
    # and re-serialising with the same options must reproduce the flag-off file
    # exactly, wall-clock fields aside.
    def _normalise(text):
        d = json.loads(text)
        d.pop("combat", None)
        d["generated_at"] = "PINNED"
        d["week_date"] = "PINNED"
        return json.dumps(d, indent=2, ensure_ascii=False)

    assert _normalise(on_text) == _normalise(off_text)


def test_shipped_flag_is_on():
    """What actually ships. The counterpart to the rollback test above."""
    assert config.COMBAT_SOURCE_ENABLED is True
    assert config.COMBAT_TABS == {"sc": "SC Combat Teams", "li": "LI Combat Teams"}
