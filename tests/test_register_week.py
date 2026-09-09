"""The register carries this week's assignments (``build._attach_week``).

data.json and index.html answer "what does each member have"; trials.json answers
"what is each member doing this week". These tests pin the projection that puts the
second answer on the first artefact: a top-level ``week`` block, a ``trial`` stamp on
every register member, and — the point of the exercise — that trials.json is not
touched on the way past. See config.REGISTER_CARRIES_WEEK.
"""

import copy
import json

from src import build, config, processor, trials
from src.reader import MemberRow, SkillEntry

# Two trials with cap=4 over ten members leaves a bench, which is what most of these
# tests need: assigned, benched and (constructed) unassigned all in one week.
SKILLS = ["Foraging", "Brewing"]


def _member(name, level=100):
    """A manual-tab member with the same value in every skill."""
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
    # Distinct levels so the optimiser's choice is not a tie-break coin toss.
    return [_member(f"m{i}", 90 + i) for i in range(10)]


def _week(members, cap=4):
    """Deterministic: ``trials.run_week`` with a fixed seed and the random split."""
    return trials.run_week(
        members, skills=list(SKILLS), seed=7, cap=cap, strategy="random"
    ).to_dict()


def _inputs(site, members, register):
    return build._GuildInputs(
        site_key=site.key,
        members=members,
        register=register,
        picks=None,
        signup_unavailable="not in this test",
        signup_unavailable_short="test",
    )


def _draw():
    return build.draw_model.TrialDraw(skills=list(SKILLS), date="")


def test_every_register_member_is_stamped_exactly_once():
    members = _ten()
    week = _week(members)
    register = processor.process(members)

    build._attach_week(register, week, "")
    block = register["week"]

    seated = {r["name"] for t in week["trials"] for r in t["roster"]}
    benched = set(week["bench"])
    assert seated & benched == set()
    assert seated | benched == {m.name for m in members}

    for m in register["members"]:
        stamp = m["trial"]
        if m["name"] in benched:
            assert stamp == {"skill": None, "status": "bench"}
        else:
            assert stamp["status"] == "assigned"
            party = next(p for p in block["parties"] if p["skill"] == stamp["skill"])
            assert m["name"] in party["members"]

    for party, trial in zip(block["parties"], week["trials"]):
        assert party["members"] == [
            r["name"] for r in build._sorted_roster(trial)
        ]
        assert party["party_size"] == len(party["members"])

    assert block["bench"] == week["bench"]
    assert block["unassigned"] == []
    assert block["not_on_register"] == []


def test_the_block_copies_and_trials_json_is_untouched():
    members = _ten()
    week = _week(members)
    register = processor.process(members)

    before = json.dumps(week, sort_keys=True)
    build._attach_week(register, week, "")
    assert json.dumps(week, sort_keys=True) == before

    # Copies, never aliases: trials.json is the authoritative record, so nothing done
    # to the register may reach back into it.
    register["week"]["bench"].append("intruder")
    register["week"]["skills"].append("Cheesesmithing")
    register["week"]["parties"][0]["members"].append("intruder")
    assert json.dumps(week, sort_keys=True) == before


def test_a_seated_name_with_no_register_row_is_listed_not_dropped():
    nine = _ten()[:9]
    admitted = _member("AmamiyaKokoro", 99)
    week = _week(nine + [admitted])
    register = processor.process(nine)

    build._attach_week(register, week, "")
    block = register["week"]

    everywhere = {n for p in block["parties"] for n in p["members"]} | set(
        block["bench"]
    )
    assert "AmamiyaKokoro" in everywhere
    assert block["not_on_register"] == ["AmamiyaKokoro"]
    # index.html mirrors the officers' tab: no row is grown for a roster-only member.
    assert [m["name"] for m in register["members"]] == [m.name for m in nine]
    assert block["unassigned"] == []


def test_a_register_member_the_optimiser_never_saw_is_unassigned_and_warned(
    tmp_path, monkeypatch, capsys
):
    members = _ten()
    week = _week(members)
    register = processor.process(members + [_member("ghost", 50)])

    build._attach_week(register, copy.deepcopy(week), "")
    ghost = next(m for m in register["members"] if m["name"] == "ghost")
    assert ghost["trial"] == {"skill": None, "status": "unassigned"}
    assert register["week"]["unassigned"] == ["ghost"]

    monkeypatch.setattr(build, "OUTPUT_DIR", tmp_path)
    site = build.GUILD_SITES[0]
    fresh = processor.process(members + [_member("ghost", 50)])
    build._write_guild(site, _inputs(site, members, fresh), week, None, _draw(), "")
    err = capsys.readouterr().err
    assert "stamped 'unassigned'" in err
    assert "ghost" in err


def test_the_join_is_case_insensitive_but_refuses_ambiguity():
    nine = _ten()[:9]
    week = _week(nine + [_member("Dome", 99)])

    matched = processor.process(nine + [_member("dome", 99)])
    build._attach_week(matched, copy.deepcopy(week), "")
    dome = next(m for m in matched["members"] if m["name"] == "dome")
    assert dome["trial"]["status"] in {"assigned", "bench"}
    assert matched["week"]["not_on_register"] == []
    assert matched["week"]["unassigned"] == []

    # roster.join's rule: a normalised key held by two distinct raw names on either
    # side matches nobody through normalisation. Better no stamp than a wrong one.
    ambiguous = processor.process(nine + [_member("dome", 99), _member("DOME", 98)])
    build._attach_week(ambiguous, copy.deepcopy(week), "")
    for name in ("dome", "DOME"):
        m = next(x for x in ambiguous["members"] if x["name"] == name)
        assert m["trial"] == {"skill": None, "status": "unassigned"}
    assert ambiguous["week"]["unassigned"] == ["dome", "DOME"]
    assert ambiguous["week"]["not_on_register"] == ["Dome"]


def test_a_stale_draw_is_flagged_in_the_block_and_bannered_on_the_page():
    members = _ten()
    week = _week(members)

    warning = "Draw tab unreadable; using the last known draw. MAY BE STALE."
    stale = processor.process(members)
    build._attach_week(stale, copy.deepcopy(week), warning)
    assert stale["week"]["draw_stale"] is True
    assert stale["week"]["draw_warning"] == warning

    page = build._render_html(stale, build.GUILD_SITES[0])
    assert "Draw may be stale." in page
    assert page.index("Draw may be stale.") < page.index("This week's trials")

    live = processor.process(members)
    build._attach_week(live, copy.deepcopy(week), "")
    assert live["week"]["draw_stale"] is False
    assert live["week"]["draw_warning"] == ""
    assert "Draw may be stale." not in build._render_html(live, build.GUILD_SITES[0])


def test_the_register_page_shows_the_trial_column_and_section():
    members = _ten()
    week = _week(members)
    register = processor.process(members)
    build._attach_week(register, copy.deepcopy(week), "")
    page = build._render_html(register, build.GUILD_SITES[0])

    assert "<th>Trial</th>" in page
    assert "This week's trials" in page
    benched = set(register["week"]["bench"])
    assert benched, "this fixture is meant to leave a bench"
    assert 'class="trialcell muted">bench<' in page
    assert any(f'class="trialcell">{s}<' in page for s in SKILLS)
    assert "Also seated, but not on this tab" not in page

    nine = members[:9]
    admitted_week = _week(nine + [_member("AmamiyaKokoro", 99)])
    admitted = processor.process(nine)
    build._attach_week(admitted, admitted_week, "")
    admitted_page = build._render_html(admitted, build.GUILD_SITES[0])
    assert "Also seated, but not on this tab: AmamiyaKokoro." in admitted_page


def test_week_none_writes_null_and_renders_the_page_as_before():
    register = processor.process(_ten())
    before = build._render_html(copy.deepcopy(register), build.GUILD_SITES[0])

    build._attach_week(register, None, "")
    assert register["week"] is None
    assert all("trial" not in m for m in register["members"])
    after = build._render_html(register, build.GUILD_SITES[0])
    assert after == before


def test_write_guild_publishes_the_week_on_both_guilds_and_leaves_trials_json_alone(
    tmp_path, monkeypatch
):
    # This test pins what the REGISTER projection does to trials.json (nothing but
    # provenance). The `combat` key is a different feature with its own on/off pin in
    # tests/test_combat.py, so it is switched off here rather than folded into the
    # expectation below.
    monkeypatch.setattr(config, "COMBAT_SOURCE_ENABLED", False)
    monkeypatch.setattr(build, "OUTPUT_DIR", tmp_path)
    members = _ten()

    for site in build.GUILD_SITES:
        week = _week(members)
        keys_before = set(week)
        register = processor.process(members)
        build._write_guild(
            site, _inputs(site, members, register), week, None, _draw(), ""
        )

        out = site.out_dir
        data = json.loads((out / "data.json").read_text(encoding="utf-8"))
        published = json.loads((out / build.TRIALS_JSON).read_text(encoding="utf-8"))

        assert data["week"]["generated_at"] == published["generated_at"]
        assert all("trial" in m for m in data["members"])
        # trials.json gains the provenance block every artefact gets, and nothing else.
        assert set(published) == keys_before | {"provenance"}
        # The stamp key, not the substring: "trials" is trials.json's own top-level
        # list, so the naive `"trial" not in ...` would always fire.
        assert '"trial":' not in json.dumps(published)
        assert data["provenance"] == published["provenance"]

    assert (tmp_path / "data.json").exists()
    assert (tmp_path / "li" / "data.json").exists()


def test_flag_off_is_byte_identical_and_on_is_additive(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "OUTPUT_DIR", tmp_path)
    site = build.GUILD_SITES[0]
    members = _ten()

    def run():
        register = processor.process(members)
        build._write_guild(
            site, _inputs(site, members, register), _week(members), None, _draw(), ""
        )
        return (
            json.loads((tmp_path / "data.json").read_text(encoding="utf-8")),
            (tmp_path / "index.html").read_text(encoding="utf-8"),
        )

    monkeypatch.setattr(config, "REGISTER_CARRIES_WEEK", False)
    off, off_page = run()
    monkeypatch.setattr(config, "REGISTER_CARRIES_WEEK", True)
    on, on_page = run()

    assert set(off) == {
        "generated_at",
        "member_count",
        "skills",
        "skill_summary",
        "members",
        "provenance",
    }
    assert set(on) - set(off) == {"week"}
    for off_m, on_m in zip(off["members"], on["members"]):
        assert set(on_m) - set(off_m) == {"trial"}
        assert all(off_m[k] == on_m[k] for k in off_m)
    assert off["member_count"] == on["member_count"]

    assert "<th>Trial</th>" not in off_page
    assert 'class="alert"' not in off_page
    assert "<th>Trial</th>" in on_page
