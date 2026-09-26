"""The build's guild-building plumbing: the parent resolves, the child receives.

Narrow by design. ``build.py`` is 5,000 lines of rendering and orchestration and has
no test module of its own; this one exists for the single property that the
2026-09-09 buildings source risks and nothing else covers — that binding
``config.GUILD_BUILDING_LEVELS`` for the duration of an optimiser unit cannot leak
one guild's levels into another's week.

WHY THAT NEEDS A TEST RATHER THAN AN ARGUMENT. ``_compute_unit`` is normally a
process of its own, which makes the binding trivially safe. But ``_run_units`` falls
back to running every job IN THIS PROCESS when ``config.BUILD_PARALLEL`` is off or
there is a single job — and units of different guilds share that process. The
restore in ``trials.guild_building_levels_scope`` is what makes that safe, so it is
pinned here in exactly the arrangement that would expose its absence.
"""

import pytest

from src import build, config
from src.reader import MemberRow, SkillEntry


def _member(name: str, level: int) -> MemberRow:
    return MemberRow(
        name=name,
        main_classes="",
        flex="",
        flex_levels=[],
        skills={
            "Foraging": SkillEntry(level=level, tool=False, top=False, bot=False,
                                   house=4),
        },
    )


def _job(building_levels: dict, cap: int = 12) -> dict:
    return {
        "site_key": "sc",
        "members": [_member(f"M{i}", 100) for i in range(20)],
        "skills": ["Foraging"],
        "min_levels": {},
        "cap": cap,
        "shrine_caps": config.shrine_caps("sc"),
        "building_levels": building_levels,
        "level": 1,
        "picks": None,
    }


def test_sequential_units_do_not_leak_levels_between_guilds(monkeypatch):
    """Two guilds, one process, different levels. Each week records its own.

    The failure this catches is the quiet kind: LI's page silently planned on SC's
    Guild Observatory. Both weeks would render, both would look plausible, and only
    the tier totals would be wrong.
    """
    monkeypatch.setattr(config, "BUILD_PARALLEL", False)
    saved = config.GUILD_BUILDING_LEVELS
    per_level = config.GUILD_BUILDING_SKILL_LEVELS_PER_LEVEL

    results = build._run_units([_job({"Foraging": 5}), _job({})])

    assert results[0]["week"]["guild_building_levels"] == {"Foraging": 5 * per_level}
    # The second guild has NO observation, so it must fall back to the configured
    # zeros — not inherit the first guild's five levels.
    assert results[1]["week"]["guild_building_levels"] == {"Foraging": 0}
    # And nothing is left bound afterwards, for the renderer that runs next.
    assert config.GUILD_BUILDING_LEVELS is saved


def test_a_failing_unit_does_not_leave_levels_bound(monkeypatch):
    """The restore covers the exception path, which is the path that matters.

    An optimiser error propagates out of ``_run_units`` and the parent goes on to
    render the guilds that did succeed — so levels left bound by a failed unit would
    contaminate a page built afterwards.

    The failure is injected at ``run_week`` rather than contrived from bad input,
    because the model TOLERATES bad input: an unknown skill name simply reads as
    blank levels and produces a week. An earlier draft of this test passed for that
    reason while exercising nothing.
    """
    monkeypatch.setattr(config, "BUILD_PARALLEL", False)
    saved = config.GUILD_BUILDING_LEVELS

    def boom(*args, **kwargs):
        # Asserted mid-flight: the levels ARE bound at the moment of failure, so the
        # restore afterwards is a real restore and not a no-op.
        assert config.GUILD_BUILDING_LEVELS["Foraging"] == 9
        raise RuntimeError("the optimiser fell over")

    monkeypatch.setattr(build.trials_model, "run_week", boom)
    monkeypatch.setattr(config, "TRIALS_BUFF_LEVEL_SLIDER", False)

    with pytest.raises(RuntimeError):
        build._run_units([_job({"Foraging": 9})])

    assert config.GUILD_BUILDING_LEVELS is saved


def test_unit_jobs_ship_the_fetched_levels():
    """The link between the fetch and the unit — the one that could actually break.

    ``_compute_unit`` reads this key with ``.get`` (absent means "no observation"),
    so a dropped key would NOT raise: it would quietly plan every guild on the
    configured zeros. Hence a test on the shipping side rather than the reading one.
    """
    from src import draw as draw_model

    site = build.GUILD_SITES[0]
    inputs = build._GuildInputs(
        site_key=site.key,
        members=[_member("M0", 100)],
        register={"member_count": 1, "skills": []},
        picks=None,
        building_levels={"Enhancing": 1},
        buildings_captured_at="2026-09-09T13:00:53.934Z",
    )
    week_draw = draw_model.TrialDraw(skills=["Foraging"], date="", min_levels={})
    jobs = build._unit_jobs(site, inputs, week_draw)

    assert jobs, "at least the published unit"
    for job in jobs:
        assert job["building_levels"] == {"Enhancing": 1}


# ---------------------------------------------------------------------------
# the CI summary's buildings clause
# ---------------------------------------------------------------------------
def _summary_inputs(**kw) -> "build._GuildInputs":
    base = dict(
        site_key="sc",
        members=[_member("M0", 100)],
        register={"member_count": 1, "skills": []},
        picks=None,
        plan_dict=None,
        signup_unavailable_short="n/a",
    )
    base.update(kw)
    return build._GuildInputs(**base)


def _summary_week(granted: dict) -> dict:
    return {
        "guild_building_levels": granted,
        "trials": [{"skill": "Enhancing", "tier_reached": 10,
                    "partial_fraction": 0.37, "credit_points": 1118.3}],
        "total_credit_points": 1118.3,
        "total_points": 1000,
        "community_buff_level": 1,
    }


def test_the_summary_reports_granted_levels_not_building_levels():
    """The +2 is already applied; applying it twice reported a level-1 Observatory
    as "Enhancing+4".

    ``WeekResult.guild_building_levels`` is built through
    ``trials.guild_building_skill_levels``, so it holds GRANTED SKILL LEVELS. The
    first draft of this clause multiplied by
    ``GUILD_BUILDING_SKILL_LEVELS_PER_LEVEL`` again — caught only by reading the
    actual build output, which is why it is pinned here.
    """
    from src import draw as draw_model

    line = build._summary_line(
        build.GUILD_SITES[0],
        _summary_inputs(buildings_captured_at="2026-09-09T13:00:53.934Z"),
        _summary_week({"Enhancing": 2, "Milking": 0}),
        None,
        draw_model.TrialDraw(skills=["Enhancing"], date="", min_levels={}),
    )
    assert "buildings 2026-09-09 Enhancing+2" in line
    assert "Enhancing+4" not in line
    assert "Milking" not in line          # unbuilt skills are not listed


def test_the_summary_says_why_when_nothing_was_read():
    """A source that went silent must be visible in the CI log, not only on the page."""
    from src import draw as draw_model

    line = build._summary_line(
        build.GUILD_SITES[1],
        _summary_inputs(
            site_key="li",
            buildings_unavailable="The 'LI Buildings' tab exists but has never been written.",
        ),
        _summary_week({"Enhancing": 0}),
        None,
        draw_model.TrialDraw(skills=["Enhancing"], date="", min_levels={}),
    )
    assert "buildings NONE READ" in line
    assert "never been written" in line


# ---------------------------------------------------------------------------
# the combat block's loadout keys
# ---------------------------------------------------------------------------
def test_the_combat_block_always_carries_both_loadout_keys():
    """"FIVE KEYS, ALWAYS THE SAME FIVE" became seven, and the "always" is the point.

    `_combat_block` is the one place the userscript's contract is fixed, and its
    promise was never "five keys when things go well". A consumer must not have to ask
    whether `loadouts` exists before asking whether it is populated, because the two
    questions have different answers on different days and only one of them is
    interesting. So on the UNAVAILABLE path — no observation at all, which is what a
    missing tab, a stale tab and a disabled flag all reduce to — both keys are still
    emitted, with `by_id` empty and `shape` stated.

    `shape` is literal for a reason worth not rediscovering: the values inside carry
    `hrid`, the engine DTO's spelling, and not `itemHrid`, the UI's. A consumer that
    does not recognise the shape must refuse the loadouts rather than guess which
    spelling it is holding.
    """
    site = build.GUILD_SITES[0]
    block = build._combat_block(_summary_inputs(combat=None), site)

    assert block["available"] is False
    assert block["loadout_schema"] == 1
    assert block["loadouts"] == {"shape": "engine-dto", "by_id": {}}
    assert block["trials"] == []
    assert set(block) == {
        "available", "unavailable", "source", "generated_at",
        "loadout_schema", "loadouts", "trials",
    }


# ---------------------------------------------------------------------------
# the party cap, read off the Skilling Encampment (2026-09-26)
# ---------------------------------------------------------------------------
def _observation(encampment_level=None, observed=True):
    from src import buildings as buildings_model

    other = (
        {config.SKILLING_ENCAMPMENT_HRID: encampment_level}
        if encampment_level is not None
        else {}
    )
    return buildings_model.GuildBuildings(
        tab="LI Buildings",
        guild_key="li",
        observed=observed,
        captured_at="2026-09-26T08:52:00.000Z" if observed else "",
        other_levels=other if observed else {},
    )


def test_encampment_level_four_seats_twenty_eight():
    """The measured point: both guilds at level 4, and both seat 28 in game."""
    cap = config.derived_party_cap("li", 4)
    assert cap.cap == 28
    assert cap.encampment_level == 4
    assert cap.warning == ""
    assert "Skilling Encampment level 4" in cap.source


def test_no_encampment_level_falls_back_to_the_constant_and_says_so():
    """An unobserved tab has no level, and the fallback must be loud, not silent."""
    cap = config.derived_party_cap("li", None)
    assert cap.cap == config.party_cap("li")
    assert cap.encampment_level is None
    assert cap.warning
    assert "TRIAL_PARTY_CAPS" in cap.source


def test_an_unmapped_level_falls_back_to_the_constant_and_warns():
    """Level 9 is not in the map: no extrapolation, the constant, and a warning."""
    assert 9 not in config.SKILLING_ENCAMPMENT_SEATS
    cap = config.derived_party_cap("sc", 9)
    assert cap.cap == config.party_cap("sc")
    assert cap.encampment_level == 9
    assert "9" in cap.warning
    assert "TRIAL_PARTY_CAPS" in cap.source


def test_an_unmapped_level_below_the_map_never_guesses_upward():
    """A cap too HIGH seats phantom contributors. Seats cannot fall as the level
    rises (the game adds skillingTrialSlotsPerLevel per level), so an unmapped
    level below a mapped one is capped at that mapped level's seats — never the
    fallback constant when the constant is larger."""
    lowest = min(config.SKILLING_ENCAMPMENT_SEATS)
    cap = config.derived_party_cap("li", lowest - 1)
    assert cap.cap <= config.SKILLING_ENCAMPMENT_SEATS[lowest]
    assert cap.cap <= config.party_cap("li")
    assert cap.warning


def test_the_encampment_map_agrees_with_the_games_per_level_increment():
    """Every mapped pair must step by the game's skillingTrialSlotsPerLevel (2).
    A typo'd entry would break this before it broke a page."""
    levels = sorted(config.SKILLING_ENCAMPMENT_SEATS)
    seats = config.SKILLING_ENCAMPMENT_SEATS
    for lo, hi in zip(levels, levels[1:]):
        assert seats[hi] - seats[lo] == (
            config.SKILLING_ENCAMPMENT_SLOTS_PER_LEVEL * (hi - lo)
        )


def test_resolve_party_cap_reads_the_encampment_off_the_observation(capsys):
    site = build.GUILD_SITES[1]
    cap = build._resolve_party_cap(site, _observation(4))
    assert cap.cap == 28
    assert "WARNING" not in capsys.readouterr().err


def test_resolve_party_cap_on_an_unobserved_tab_warns_in_the_build_output(capsys):
    site = build.GUILD_SITES[1]
    cap = build._resolve_party_cap(site, _observation(observed=False))
    assert cap.cap == config.party_cap(site.key)
    assert f"WARNING ({site.key})" in capsys.readouterr().err

    # No observation at all (flag off, or the tab was unreadable): same answer.
    cap = build._resolve_party_cap(site, None)
    assert cap.cap == config.party_cap(site.key)
    assert f"WARNING ({site.key})" in capsys.readouterr().err


def test_resolve_party_cap_on_an_unmapped_level_warns_in_the_build_output(capsys):
    site = build.GUILD_SITES[0]
    cap = build._resolve_party_cap(site, _observation(9))
    assert cap.cap == config.party_cap(site.key)
    err = capsys.readouterr().err
    assert f"WARNING ({site.key})" in err and "9" in err


def test_unit_jobs_ship_the_derived_cap_not_the_constant():
    """The guild's jobs plan at the cap derived from ITS encampment. 24 is a value
    no constant holds, so a job that reverted to site.party_cap fails here."""
    from src import draw as draw_model

    site = build.GUILD_SITES[1]
    derived = config.PartyCap(
        cap=24, source="Skilling Encampment level 2 (test)", encampment_level=2,
    )
    inputs = build._GuildInputs(
        site_key=site.key,
        members=[_member("M0", 100)],
        register={"member_count": 1, "skills": []},
        picks=None,
        party_cap=derived,
    )
    week_draw = draw_model.TrialDraw(skills=["Foraging"], date="", min_levels={})
    for job in build._unit_jobs(site, inputs, week_draw):
        assert job["cap"] == 24


def test_unit_jobs_without_a_derived_cap_use_the_guild_constant():
    """Inputs built without one (older tests, direct callers) keep the old answer."""
    from src import draw as draw_model

    site = build.GUILD_SITES[1]
    inputs = build._GuildInputs(
        site_key=site.key,
        members=[_member("M0", 100)],
        register={"member_count": 1, "skills": []},
        picks=None,
    )
    week_draw = draw_model.TrialDraw(skills=["Foraging"], date="", min_levels={})
    for job in build._unit_jobs(site, inputs, week_draw):
        assert job["cap"] == site.party_cap


def test_the_cap_source_is_in_provenance_and_the_summary():
    """A wrong seat count must be visible: in trials.json and in the CI line."""
    from src import draw as draw_model

    derived = config.derived_party_cap("li", 4)
    inputs = _summary_inputs(site_key="li", party_cap=derived)
    prov = build._provenance_block(inputs)
    assert prov["party_cap"] == 28
    assert "Skilling Encampment level 4" in prov["party_cap_source"]

    line = build._summary_line(
        build.GUILD_SITES[1],
        inputs,
        _summary_week({"Enhancing": 0}),
        None,
        draw_model.TrialDraw(skills=["Enhancing"], date="", min_levels={}),
    )
    assert "seats 28 (encampment L4)" in line
