"""Uploaded profiles (src/profiles.py): parse, refusals, precedence, fallback.

Every row here is SYNTHETIC. Never paste a real profile row into this file.
"""

import json

import pytest

from src import config, profiles, roster
from src.reader import MemberRow, SkillEntry

HEADER = list(profiles.PROFILE_HEADER) + ["trackedSet"]
TOKEN = "s3cr3t-token/with+chars"
# Captured at import, before conftest stubs it out for every test.
_REAL_LOAD_CREDENTIALS = profiles.load_credentials
URL = "https://script.google.com/macros/s/AKfycbFAKEDEPLOYMENTID/exec"


def _row(cid="42", skills="milking:120;alchemy:95", items="", houses="dairy_barn:5",
         captured="2026-10-20T00:00:00Z"):
    row = [""] * len(HEADER)
    row[0], row[1], row[3] = cid, "Synthetic", captured
    row[5], row[8], row[15] = skills, items, houses
    row[7] = "celestial_brush:20"  # `equipped` must never be read
    return row


def _body(rows, **over):
    body = {"ok": True, "tab": "SC Profiles", "header": HEADER, "rows": rows,
            "rowCount": len(rows), "truncated": False, "maxRows": 2000}
    body.update(over)
    return body


# --- parse ------------------------------------------------------------------
def test_parse_maps_skills_houses_and_best_owned_tool():
    items = "rainbow_brush:5;holy_brush:2;cheese_brush:10;dairyhands_top:3;sword:9"
    got = profiles.parse(_body([_row(items=items)]))[42]
    assert got.levels == {"Milking": 120, "Bell Farming": 95}
    assert got.houses == {"Milking": 5}
    # Best OWNED by modelled value (Holy+2 > Rainbow+5 > Cheese+10), never `equipped`.
    assert got.tools == {"Milking": ("Holy Brush", 2)}
    assert got.gear == {"/items/dairyhands_top": 3}


def test_blank_items_owns_none_absent_items_unknown():
    assert profiles.parse(_body([_row(items="")]))[42].gear == {}
    short = _row()[:5]  # the row stops before `items`
    assert profiles.parse(_body([short]))[42].gear is None


def test_duplicate_id_keeps_newest_and_idless_rows_drop():
    old = _row(skills="milking:100", captured="2026-10-01")
    new = _row(skills="milking:110", captured="2026-10-02")
    got = profiles.parse(_body([new, old, _row(cid="")]))
    assert list(got) == [42] and got[42].levels["Milking"] == 110


def test_shifted_header_is_refused():
    header = list(HEADER)
    header[5], header[6] = header[6], header[5]
    with pytest.raises(profiles.ProfileError, match="SHIFTED"):
        profiles.parse(_body([_row()], header=header))


@pytest.mark.parametrize("raw, match", [
    ("<!DOCTYPE html><html>sign in</html>", "HTML"),
    ("not json", "not JSON"),
    (json.dumps({"ok": False, "error": "unauthorised"}), "ok:false"),
    (json.dumps(_body([], truncated=True)), "TRUNCATED"),
])
def test_bad_responses_are_never_data(raw, match):
    with pytest.raises(profiles.ProfileError, match=match):
        profiles.accept_response(raw, "where")


# --- load: the fallback, and the secrets ------------------------------------
def test_no_credentials_means_no_profiles():
    got, note = profiles.load("SC Profiles")
    assert got is None and "no credentials" in note


def test_failed_read_falls_back_and_never_leaks_the_secrets(monkeypatch):
    monkeypatch.setattr(profiles, "load_credentials", lambda: (URL, TOKEN))
    monkeypatch.setattr(profiles.time, "sleep", lambda s: None)

    def boom(req, timeout):
        raise OSError(f"failed {req.full_url}")

    monkeypatch.setattr(profiles.urllib.request, "urlopen", boom)
    got, note = profiles.load("SC Profiles")
    assert got is None and "unreadable" in note
    for secret in (TOKEN, URL, "AKfycb", "s3cr3t"):
        assert secret not in note


def test_html_answer_falls_back(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return f"<html>{TOKEN}</html>".encode()

    monkeypatch.setattr(profiles, "load_credentials", lambda: (URL, TOKEN))
    monkeypatch.setattr(profiles.time, "sleep", lambda s: None)
    monkeypatch.setattr(profiles.urllib.request, "urlopen", lambda r, timeout: Resp())
    got, note = profiles.load("SC Profiles")
    assert got is None and "HTML" in note and "s3cr3t" not in note


def test_env_credentials_win(monkeypatch, tmp_path):
    monkeypatch.setattr(profiles, "load_credentials", _REAL_LOAD_CREDENTIALS)
    monkeypatch.setattr(profiles, "LOCAL_CREDENTIALS", tmp_path / "missing.json")
    monkeypatch.delenv(profiles.URL_ENV, raising=False)
    monkeypatch.delenv(profiles.TOKEN_ENV, raising=False)
    assert profiles.load_credentials() is None
    monkeypatch.setenv(profiles.URL_ENV, URL)
    monkeypatch.setenv(profiles.TOKEN_ENV, TOKEN)
    assert profiles.load_credentials() == (URL, TOKEN)


# --- precedence (roster._merged_entry) ---------------------------------------
def _rrow(level=None, house=None, tool=None, enh=None):
    return roster.RosterRow(
        name="Synthetic", character_id="42", captured_at="", revision="",
        levels={"Milking": level}, houses={"Milking": house},
        tools={"Milking": tool}, tool_enh={"Milking": enh},
    )


def _prof(**kw):
    return profiles.ProfileRow(character_id=42, **kw)


def _merge(entry, row, prof):
    tags = {}
    out = roster._merged_entry(entry, row, "Milking", tags, roster.Provenance(), prof)
    return out, tags


MANUAL = SkillEntry(level=90, tool=True, top=False, bot=False, house=2)


def test_higher_of_profile_and_manual_wins():
    out, tags = _merge(MANUAL, None, _prof(levels={"Milking": 80}, houses={"Milking": 3}))
    assert (out.level, tags["Milking.level"]) == (90, "manual")
    assert (out.house, tags["Milking.house"]) == (3, "profiles")


def test_profile_without_modelled_gear_leaves_the_roster_cell(monkeypatch):
    monkeypatch.setattr(config, "GEAR_SOURCE_ENABLED", True)
    assert roster._gear_cell(None, _prof(gear={})) is None
    row = _rrow()
    row.gear = {"/items/dairyhands_top": 1}
    assert roster._gear_cell(row, _prof(gear={})) is row.gear


def test_profile_tool_badge_names_nothing():
    from src import build
    badge = build._tool_badge({"tool_source": "profiles", "tool_item": None})
    assert "uploaded profile" in badge and "Brush" not in badge


def test_older_profile_never_lowers_the_roster():
    row = _rrow(level=130, house=6, tool="Holy Brush", enh=8)
    prof = _prof(levels={"Milking": 120}, houses={"Milking": 7},
                 tools={"Milking": ("Holy Brush", 5)})
    out, tags = _merge(MANUAL, row, prof)
    assert (out.level, tags["Milking.level"]) == (130, "roster")
    assert (out.house, tags["Milking.house"]) == (7, "profiles")
    assert (out.tool_item, out.tool_enhance, tags["Milking.tool"]) == (
        "Holy Brush", 8, "roster")


def test_better_owned_tool_wins_and_is_tagged_profiles():
    row = _rrow(tool="Rainbow Brush", enh=10)
    prof = _prof(tools={"Milking": ("Celestial Brush", 0)},
                 gear={"/items/dairyhands_top": 2})
    out, tags = _merge(MANUAL, row, prof)
    assert (out.tool_item, out.tool_enhance) == ("Celestial Brush", 0)
    assert tags["Milking.tool"] == "profiles"
    assert out.top is True and out.bot is False


def test_merge_joins_profiles_by_character_id_only(monkeypatch):
    monkeypatch.setattr(config, "ROSTER_MIN_JOIN_RATE", 0.0)
    member = MemberRow(
        name="Synthetic", main_classes="", flex="", flex_levels=[],
        skills={s: SkillEntry(level=90, tool=False, top=False, bot=False, house=2)
                for s in config.SKILLS},
        character_id="42",
    )
    other = MemberRow(
        name="Other", main_classes="", flex="", flex_levels=[],
        skills={s: SkillEntry(level=90, tool=False, top=False, bot=False, house=2)
                for s in config.SKILLS},
    )
    profs = {42: _prof(levels={"Milking": 150}, gear={"/items/dairyhands_top": 4})}
    merged, prov = roster.merge(
        [member, other], roster.JoinReport(), "sc", profs, "1 profiles read")
    assert merged[0].skills["Milking"].level == 150
    assert merged[0].provenance["Milking.level"] == "profiles"
    assert merged[1].skills["Milking"].level == 90
    assert prov.profile_backed == 1 and prov.to_dict()["profiles"] == "1 profiles read"
    if config.GEAR_SOURCE_ENABLED:
        assert merged[0].gear == {"/items/dairyhands_top": 4}


def test_switch_off_restores_the_manual_value(monkeypatch):
    monkeypatch.setattr(config, "ROSTER_USE_TOOLS", False)
    out, tags = _merge(MANUAL, None, _prof(tools={"Milking": ("Holy Brush", 5)}))
    assert out.tool_item is None and tags["Milking.tool"] == "manual"


def test_refused_roster_still_applies_profiles(monkeypatch):
    monkeypatch.setattr(config, "ROSTER_MIN_JOIN_RATE", 1.0)
    member = MemberRow(
        name="Synthetic", main_classes="", flex="", flex_levels=[],
        skills={s: SkillEntry(level=90, tool=False, top=False, bot=False, house=2)
                for s in config.SKILLS},
        character_id="42",
    )
    report = roster.JoinReport(unmatched_roster=["Stranger"],
                               roster_only=[_rrow(level=200)])
    merged, prov = roster.merge(
        [member], report, "sc", {42: _prof(levels={"Milking": 150})}, "")
    assert prov.refused and prov.admitted == 0 and len(merged) == 1
    assert merged[0].skills["Milking"].level == 150
    assert prov.reported_not_seated == ["Stranger"]


def test_overflowing_pair_is_skipped_not_fatal():
    assert profiles.parse_pairs("milking:1e400;foraging:inf;woodcutting:7") == {
        "woodcutting": 7}


def test_permanent_http_refusal_is_not_retried(monkeypatch):
    calls = []

    def forbidden(req, timeout):
        calls.append(1)
        raise profiles.urllib.error.HTTPError(req.full_url, 403, "no", {}, None)

    monkeypatch.setattr(profiles.time, "sleep", lambda s: None)
    monkeypatch.setattr(profiles.urllib.request, "urlopen", forbidden)
    with pytest.raises(profiles.ProfileError, match="HTTP 403") as err:
        profiles.fetch("SC Profiles", URL, TOKEN)
    assert len(calls) == 1 and "AKfycb" not in str(err.value)
