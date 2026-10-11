"""Rename safety, end to end (hazard J): a member renamed in-game (OLD -> NEW, same
characterId) is never departed, unmatched or admitted, and is logged as
``renamed OLD → NEW (id N)``. Old tabs without id columns behave exactly as before.
"""

from __future__ import annotations

import pytest

from src import build, combat, config, identity, processor, roster, trials
from src import draw as draw_model
from src.reader import MemberRow, SkillEntry

SKILLS4 = ["Milking", "Cooking", "Woodcutting", "Enhancing"]
HEADER = "User,Milking,Cooking,Woodcutting,Enhancing,Badger,Swarm"
SIGNUP_WITH_IDS = (
    f"{HEADER},characterId\n"
    "NewName,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE,102437\n"
    "Other,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,555\n"
)
SIGNUP_OLD = (
    f"{HEADER}\n"
    "NewName,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE\n"
    "Other,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE\n"
)
HISTORY_CSV = (
    "Character Id,Name,Guild Id,First Seen,Last Seen\n"
    "102437,OldName,4,,\n"
    "102437,NewName,4,2026-10-01T00:00:00.000Z,2026-10-10T00:00:00.000Z\n"
)


def _member(name, level=100, cid=None):
    return MemberRow(
        name=name, main_classes="", flex="", flex_levels=[],
        skills={
            s: SkillEntry(level=level, tool=False, top=False, bot=False, house=4)
            for s in config.SKILLS
        },
        character_id=cid,
    )


def _roster_row(name, cid):
    none = {s: None for s in config.SKILLS}
    return roster.RosterRow(
        name=name, character_id=cid, captured_at="2026-10-01T00:00:00.000Z",
        revision="1", levels=dict(none), houses=dict(none), tools=dict(none),
        tool_enh=dict(none),
    )


def _stub(monkeypatch, signup_csv, roster_rows=None):
    from src import scraper

    gd = scraper.GuildData(
        tab="SC Member Data", fetched_at="t", member_count=2,
        members=[_member("OldName"), _member("Other")],
    )
    monkeypatch.setattr(config, "BUILDINGS_SOURCE_ENABLED", False)
    monkeypatch.setattr(config, "ROSTER_SOURCE_ENABLED", roster_rows is not None)
    if roster_rows is not None:
        monkeypatch.setattr(roster, "scrape_roster_tab", lambda tab: list(roster_rows))
    monkeypatch.setattr(build, "scrape_member_tab", lambda tab: gd)
    monkeypatch.setattr(build.signup_model, "fetch_signup_csv", lambda tab: signup_csv)
    monkeypatch.setattr(build, "_fetch_combat", lambda site, csv: (None, "stub"))
    monkeypatch.setattr(build, "_fetch_building_value", lambda site: (None, "stub"))
    return gd


def _fetch():
    site = [s for s in build.GUILD_SITES if s.key == "li"][0]
    return build._fetch_guild(site, draw_model.TrialDraw(skills=list(SKILLS4), date=""))


def _assert_renamed(inputs, err):
    assert [m.name for m in inputs.members] == ["NewName", "Other"]
    assert inputs.members[0].character_id == "102437"
    assert inputs.renames == {"OldName": "NewName"}
    assert "renamed OldName → NewName (id 102437)" in err
    assert "left the guild" not in err
    # The volunteer is locked under the same name the model pool now uses.
    assert inputs.picks["NewName"] == {"Milking"}
    assert "NewName" in {m.name for m in inputs.members}


def test_renamed_member_resolved_via_roster_row_is_not_departed(monkeypatch, capsys):
    _stub(monkeypatch, SIGNUP_WITH_IDS,
          [_roster_row("OldName", "102437"), _roster_row("Other", "555")])
    inputs = _fetch()
    err = capsys.readouterr().err
    _assert_renamed(inputs, err)
    # The register still mirrors the officers' tab.
    assert [m["name"] for m in inputs.register["members"]] == ["OldName", "Other"]
    # And the roster join did not admit OldName as a roster-only newcomer.
    assert inputs.roster_provenance.admitted == 0


def test_renamed_member_resolved_via_name_history(monkeypatch, capsys):
    _stub(monkeypatch, SIGNUP_WITH_IDS)
    monkeypatch.setattr(identity, "fetch_name_history_csv", lambda tab: HISTORY_CSV)
    inputs = _fetch()
    _assert_renamed(inputs, capsys.readouterr().err)


def test_old_signup_tab_without_id_column_behaves_as_today(monkeypatch, capsys):
    _stub(monkeypatch, SIGNUP_OLD)
    inputs = _fetch()
    err = capsys.readouterr().err
    assert [m.name for m in inputs.members] == ["Other"]
    assert inputs.renames == {}
    assert "left the guild" in err and "OldName" in err
    assert "renamed" not in err


def test_flag_off_is_todays_behaviour(monkeypatch, capsys):
    _stub(monkeypatch, SIGNUP_WITH_IDS,
          [_roster_row("OldName", "102437"), _roster_row("Other", "555")])
    monkeypatch.setattr(config, "ID_JOIN_ENABLED", False)
    inputs = _fetch()
    err = capsys.readouterr().err
    assert inputs.renames == {}
    assert "OldName" not in {m.name for m in inputs.members}
    assert "renamed" not in err


# --- _attach_week: the register stamp for a renamed member ---------------------
def _week_for(names):
    members = [_member(n, 90 + i) for i, n in enumerate(names)]
    return trials.run_week(
        members, skills=["Foraging", "Brewing"], seed=7, cap=4, strategy="random"
    ).to_dict()


def test_attach_week_stamps_a_renamed_register_member():
    names = ["NewName"] + [f"m{i}" for i in range(5)]
    week = _week_for(names)
    reg_members = [_member("OldName", 90)] + [_member(f"m{i}", 91 + i) for i in range(5)]

    register = processor.process(reg_members)
    build._attach_week(register, week, "", {"OldName": "NewName"})
    old = next(m for m in register["members"] if m["name"] == "OldName")
    assert old["trial"]["status"] in ("assigned", "bench")
    assert register["week"]["not_on_register"] == []

    register = processor.process(reg_members)
    build._attach_week(register, week, "")
    old = next(m for m in register["members"] if m["name"] == "OldName")
    assert old["trial"]["status"] == "unassigned"
    assert register["week"]["not_on_register"] == ["NewName"]


def test_dropped_stale_row_still_finds_its_seat_on_the_register():
    # The officers' tab lists both OldName (stale) and NewName: canonicalise drops
    # the OldName row, but the register row must not read "unassigned" every build.
    reg_members = [_member("OldName", 90), _member("NewName", 90)] + [
        _member(f"m{i}", 91 + i) for i in range(5)]
    resolver = identity.Resolver(
        roll=[("NewName", 102437)], history=[identity.HistoryRow(102437, "OldName")])
    members, renames, _ = identity.canonicalise(reg_members, resolver)
    assert "OldName" not in {m.name for m in members}
    assert renames == {"OldName": "NewName"}

    week = _week_for(["NewName"] + [f"m{i}" for i in range(5)])
    register = processor.process(reg_members)
    build._attach_week(register, week, "", renames)
    stamps = {m["name"]: m["trial"] for m in register["members"]}
    assert stamps["OldName"] == stamps["NewName"]
    assert stamps["OldName"]["status"] in ("assigned", "bench")
    assert register["week"]["unassigned"] == []


# --- _combat_block: a renamed seat is shown under its live name ----------------
def test_combat_block_refreshes_a_renamed_seat_and_carries_the_id(capsys):
    seat = combat.CombatSeat(name="OldName", role="tank", slot="tank 1",
                             character_id=102437)
    obs = combat.GuildCombat(
        tab="SC Combat Teams", guild_key="sc", observed=True,
        teams=[combat.CombatTeam(hrid="/guild_combat/badger", team="SC Team 1",
                                 roster=[seat])],
    )
    site = [s for s in build.GUILD_SITES if s.key == "sc"][0]
    inputs = build._GuildInputs(
        site_key="sc", members=[_member("NewName", cid="102437")], register={},
        picks=None, combat=obs,
    )
    block = build._combat_block(inputs, site)
    out = block["trials"][0]["roster"][0]
    assert out["name"] == "NewName" and out["characterId"] == 102437
    assert "renamed OldName → NewName (id 102437)" in capsys.readouterr().err
    # The observation itself is untouched.
    assert seat.name == "OldName"
