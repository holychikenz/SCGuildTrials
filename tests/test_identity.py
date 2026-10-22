"""src/identity.py — the characterId rules (rename safety, 2026-10)."""

from __future__ import annotations

import pytest

from src import config, identity, reader
from src.identity import HistoryRow, Resolver, canonicalise, find_member, parse_id
from src.reader import MemberRow


def _m(name, cid=None):
    return MemberRow(name=name, main_classes="", flex="", character_id=cid)


# --- parse_id ----------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (102437, 102437), ("102437", 102437), (" 7 ", 7), (1.0, 1),
    (0, None), (-3, None), ("", None), ("TRUE", None), (True, None), (False, None),
    ("12a", None), (1.5, None), (None, None), ("0", None), ("-4", None),
])
def test_parse_id_follows_the_contract(value, expected):
    assert parse_id(value) == expected


def test_find_id_column_is_by_header():
    assert identity.find_id_column(["User", "Milking", "characterId"]) == 2
    assert identity.find_id_column(["Member", " Character Id ", "x"]) == 1
    assert identity.find_id_column(["User", "Milking"]) is None


def test_with_character_id_emits_only_known_ids():
    assert identity.with_character_id({"name": "a", "character_id": None}) == {"name": "a"}
    assert identity.with_character_id({"name": "a", "character_id": "5"}) == {
        "name": "a", "characterId": 5}
    assert identity.with_character_id({"name": "a", "character_id": "Yedic"}) == {"name": "a"}
    assert "character_id" not in identity.with_character_id({"character_id": 3})


# --- Resolver ----------------------------------------------------------------

def test_resolver_live_roll_beats_history_and_roster():
    r = Resolver(roll=[("Bob", "1")], roster=[("Bob", "3")],
                 history=[HistoryRow(2, "Bob", last_seen="2026-10-01")])
    assert r.id_for("bob") == 1


def test_resolver_history_beats_roster_and_latest_last_seen_wins():
    r = Resolver(roster=[("Bob", "3")], history=[
        HistoryRow(2, "Bob", last_seen="2026-10-01T00:00:00Z"),
        HistoryRow(9, "Bob", last_seen="2026-09-01T00:00:00Z"),
        HistoryRow(8, "Bob", last_seen=""),
    ])
    assert r.id_for("Bob") == 2


def test_resolver_empty_last_seen_sorts_oldest():
    r = Resolver(history=[HistoryRow(8, "Bob", last_seen=""),
                          HistoryRow(4, "Bob", last_seen="2026-01-01")])
    assert r.id_for("Bob") == 4


def test_resolver_falls_back_to_roster():
    assert Resolver(roster=[("Bob", "3")]).id_for("BOB") == 3


def test_resolver_skips_ambiguous_live_names():
    r = Resolver(roll=[("Bob", 1), ("bob", 2)], roster=[("Bob", 7)])
    assert r.id_for("Bob") == 7


def test_resolver_current_name_comes_from_the_roll_only():
    r = Resolver(roll=[("NewName", 102437)], history=[HistoryRow(55, "Ghost")])
    assert r.current_name(102437) == "NewName"
    assert r.current_name("102437") == "NewName"
    assert r.current_name(55) is None


# --- canonicalise (hazard J) -------------------------------------------------

def test_canonicalise_renames_old_to_new_by_id():
    members = [_m("OldName"), _m("Other")]
    r = Resolver(roll=[("NewName", 102437), ("Other", 9)], roster=[("OldName", "102437")])
    out, renames, notes = canonicalise(members, r)
    assert [m.name for m in out] == ["NewName", "Other"]
    assert out[0].character_id == "102437"
    assert out[1].character_id == "9"
    assert renames == {"OldName": "NewName"}
    assert notes == ["renamed OldName → NewName (id 102437)"]


def test_canonicalise_case_only_difference_is_not_a_rename():
    members = [_m("oldname", "5")]
    out, renames, notes = canonicalise(members, Resolver(roll=[("OldName", 5)]))
    assert out[0] is members[0]
    assert renames == {} and notes == []


def test_canonicalise_drops_old_row_when_new_row_present():
    members = [_m("OldName"), _m("NewName")]
    r = Resolver(roll=[("NewName", 102437)], history=[HistoryRow(102437, "OldName")])
    out, renames, notes = canonicalise(members, r)
    assert [m.name for m in out] == ["NewName"]
    # The dropped OLD row still maps OLD -> NEW, so the officers' register row
    # under OldName finds NewName's seat instead of reading "unassigned".
    assert renames == {"OldName": "NewName"}
    assert notes and notes[0].startswith("renamed OldName → NewName (id 102437)")


def test_canonicalise_chain_rename_keeps_both_members():
    # Bob -> Carol, then Alice takes "Bob". The tab's original "Bob" row has
    # itself been renamed away, so Alice's row must not collide with it.
    members = [_m("Alice", "1"), _m("Bob", "2")]
    r = Resolver(roll=[("Bob", 1), ("Carol", 2)])
    out, renames, notes = canonicalise(members, r)
    assert [(m.name, m.character_id) for m in out] == [("Bob", "1"), ("Carol", "2")]
    assert renames == {"Alice": "Bob", "Bob": "Carol"}
    assert all("not modelled" not in n for n in notes)


def test_canonicalise_swap_keeps_both_members():
    members = [_m("Alice", "1"), _m("Bob", "2")]
    out, renames, _ = canonicalise(members, Resolver(roll=[("Bob", 1), ("Alice", 2)]))
    assert [(m.name, m.character_id) for m in out] == [("Bob", "1"), ("Alice", "2")]
    assert renames == {"Alice": "Bob", "Bob": "Alice"}


def test_canonicalise_two_rows_renamed_to_one_name_keep_the_first():
    members = [_m("Old1", "1"), _m("Old2")]
    r = Resolver(roll=[("New", 1)], history=[HistoryRow(1, "Old2")])
    out, renames, notes = canonicalise(members, r)
    assert [m.name for m in out] == ["New"]
    assert renames == {"Old1": "New", "Old2": "New"}
    assert "not modelled" in notes[1]


def test_canonicalise_never_mutates_its_input():
    a, b = _m("OldName"), _m("Other")
    members = [a, b]
    snapshot = [MemberRow(**vars(x)) for x in members]
    out, _, _ = canonicalise(members, Resolver(roll=[("NewName", 1)], roster=[("OldName", 1)]))
    assert members[0] is a and members[1] is b
    assert members == snapshot
    assert out[1] is b


def test_canonicalise_flag_off_is_a_noop(monkeypatch):
    monkeypatch.setattr(config, "ID_JOIN_ENABLED", False)
    members = [_m("OldName")]
    out, renames, notes = canonicalise(
        members, Resolver(roll=[("NewName", 1)], roster=[("OldName", 1)]))
    assert out == members and out[0] is members[0]
    assert renames == {} and notes == []


# --- find_member -------------------------------------------------------------

def test_find_member_by_id_then_name_then_norm():
    a, b = _m("OldName", "102437"), _m("Other")
    assert find_member([a, b], "NewName", 102437) is a
    assert find_member([a, b], "Other") is b
    assert find_member([a, b], "other") is b
    assert find_member([a, b], "Nobody") is None


# --- the Name History reader ---------------------------------------------------
_H = "Character Id,Name,Guild Id,First Seen,Last Seen\n"


def test_parse_name_history_reads_rows():
    rows = identity.parse_name_history(_H + "102437,OldName,4,,\n555,Other,4,a,b\n")
    assert rows == [HistoryRow(102437, "OldName", "4", "", ""), HistoryRow(555, "Other", "4", "a", "b")]


def test_parse_name_history_skips_leading_blank_lines_and_bad_rows():
    text = ",,,,\n" + _H + "x,Bad,4,,\n7,,4,,\n8,Good,4,,\n"
    assert identity.parse_name_history(text) == [HistoryRow(8, "Good", "4")]


def test_parse_name_history_empty_and_header_only():
    assert identity.parse_name_history("") == []
    assert identity.parse_name_history(_H) == []


def test_parse_name_history_wrong_tab_raises():
    from src.reader import SheetStructureError
    with pytest.raises(SheetStructureError):
        identity.parse_name_history("Name,Main Classes,Flex\nYedic,x,y\n")


def test_load_name_history_degrades(monkeypatch):
    def boom(tab):
        raise RuntimeError("403")
    monkeypatch.setattr(identity, "fetch_name_history_csv", boom)
    rows, warning = identity.load_name_history("SC Name History")
    assert rows == [] and "403" in warning

    monkeypatch.setattr(identity, "fetch_name_history_csv", lambda tab: "Member,x\n")
    rows, warning = identity.load_name_history("SC Name History")
    assert rows == [] and warning


def test_load_name_history_flag_off_makes_no_fetch(monkeypatch):
    monkeypatch.setattr(config, "NAME_HISTORY_SOURCE_ENABLED", False)

    def never(tab):
        raise AssertionError("must not fetch")
    monkeypatch.setattr(identity, "fetch_name_history_csv", never)
    assert identity.load_name_history("SC Name History") == ([], "")


def test_fetch_name_history_url_forces_one_header_row(monkeypatch):
    seen = {}

    class R:
        status_code = 200
        text = _H

        def raise_for_status(self):
            pass

    def get(url, timeout):
        seen["url"] = url
        return R()
    monkeypatch.undo()   # drop the conftest stub for this test
    monkeypatch.setattr(reader.requests, "get", get)
    assert identity.fetch_name_history_csv("SC Name History") == _H
    assert seen["url"].endswith("&headers=1") and "SC%20Name%20History" in seen["url"]


def test_resolver_history_two_ids_carried_bob_latest_wins():
    r = Resolver(history=[HistoryRow(1, "Bob", last_seen="2026-01-01"),
                          HistoryRow(2, "Bob", last_seen="2026-05-01")])
    assert r.id_for("bob") == 2


def test_canonicalise_drops_a_second_row_resolving_to_the_same_id():
    # "Bob" typed twice on the member tab: both resolve to the roll's id 7.
    members = [_m("Bob"), _m("Bob")]
    out, renames, notes = canonicalise(members, Resolver(roll=[("Bob", 7)]))
    assert [(m.name, m.character_id) for m in out] == [("Bob", "7")]
    assert renames == {}
    assert notes == ["Bob (id 7) is a second member-tab row for an id already modelled, "
                     "so it is not modelled"]
