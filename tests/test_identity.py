"""src/identity.py — the characterId rules (rename safety, 2026-10)."""

from __future__ import annotations

import pytest

from src import config, identity
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
    assert r.names_for(55) == {"Ghost"}


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
    assert renames == {}
    assert notes and notes[0].startswith("renamed OldName → NewName (id 102437)")


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
