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

    # _run_units hands a failing unit's exception back in place of its result, so
    # main() can skip an optional guild and still render the others.
    [result] = build._run_units([_job({"Foraging": 9})])
    assert isinstance(result, RuntimeError) and "fell over" in str(result)

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
    assert cap.source == "encampment L4"


def test_the_seats_are_base_plus_the_games_increment_per_level():
    """seats = SKILLING_ENCAMPMENT_BASE_SEATS + SLOTS_PER_LEVEL x level, anchored on
    the measured L4 = 28 and the client data's skillingTrialSlotsPerLevel = 2."""
    assert config.SKILLING_ENCAMPMENT_SLOTS_PER_LEVEL == 2
    assert config.SKILLING_ENCAMPMENT_BASE_SEATS == 20
    for level, seats in {1: 22, 3: 26, 4: 28, 5: 30}.items():
        cap = config.derived_party_cap("sc", level)
        assert cap.cap == seats
        assert cap.source == f"encampment L{level}"
        assert cap.warning == ""


def test_the_seat_table_and_its_clamp_are_gone():
    """One rule, not a table beside it: a second source of seats would drift."""
    assert not hasattr(config, "SKILLING_ENCAMPMENT_SEATS")


def test_no_encampment_level_falls_back_to_the_constant_and_says_so():
    """An unobserved tab has no level, and the fallback must be loud, not silent."""
    cap = config.derived_party_cap("li", None)
    assert cap.cap == config.party_cap("li")
    assert cap.encampment_level is None
    assert cap.warning
    assert cap.source.startswith("FALLBACK constant")


@pytest.mark.parametrize("level", [0, -1, -5])
def test_a_zero_or_negative_level_is_an_unread_cell_not_level_zero(level):
    """buildings._clamp_level reads a blank, garbled or negative cell as 0, and no
    guild has a level-0 encampment on a written tab. So 0 is "not read": the
    fallback constant, with a warning, never base + 0 = 20 seats."""
    cap = config.derived_party_cap("li", level)
    assert cap.cap == config.party_cap("li")
    assert cap.source.startswith("FALLBACK constant")
    assert "invalid" in cap.source
    assert "invalid" in cap.warning


def test_resolve_party_cap_reads_the_encampment_off_the_observation(capsys):
    site = build.GUILD_SITES[1]
    cap = build._resolve_party_cap(site, _observation(4))
    assert cap.cap == 28
    assert cap.source == "encampment L4"
    assert "WARNING" not in capsys.readouterr().err


def test_the_fallback_warnings_tell_the_three_causes_apart(capsys):
    """An empty or unread tab, a tab with no encampment row, and an invalid level
    cell each have a different remedy, so each says which it is."""
    site = build.GUILD_SITES[1]
    reasons = {}
    for name, obs in {
        "unread": None,
        "empty": _observation(observed=False),
        "no row": _observation(None),
        "invalid": _observation(0),
    }.items():
        cap = build._resolve_party_cap(site, obs)
        err = capsys.readouterr().err
        assert cap.cap == config.party_cap(site.key)
        assert cap.source.startswith("FALLBACK constant")
        assert f"WARNING ({site.key})" in err
        reasons[name] = (cap.source, err)

    assert "not read" in reasons["unread"][0]
    assert "empty" in reasons["empty"][0]
    assert "no Skilling Encampment row" in reasons["no row"][0]
    assert "invalid" in reasons["invalid"][0]
    assert len({src for src, _ in reasons.values()}) == 4
    assert len({err for _, err in reasons.values()}) == 4


def test_unit_jobs_ship_the_derived_cap_not_the_constant():
    """The guild's jobs plan at the cap derived from ITS encampment. 24 is a value
    no constant holds, so a job that reverted to site.party_cap fails here."""
    from src import draw as draw_model

    site = build.GUILD_SITES[1]
    derived = config.PartyCap(
        cap=24, source="encampment L2", encampment_level=2,
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
    assert prov["party_cap_source"] == "encampment L4"

    line = build._summary_line(
        build.GUILD_SITES[1],
        inputs,
        _summary_week({"Enhancing": 0}),
        None,
        draw_model.TrialDraw(skills=["Enhancing"], date="", min_levels={}),
    )
    assert "seats 28 (encampment L4)" in line


def test_a_fallback_cap_says_so_and_why_in_provenance_and_the_summary():
    from src import draw as draw_model

    fallback = config.derived_party_cap("li", 0)
    inputs = _summary_inputs(site_key="li", party_cap=fallback)
    prov = build._provenance_block(inputs)
    assert prov["party_cap_source"].startswith("FALLBACK constant")
    assert "invalid" in prov["party_cap_source"]

    line = build._summary_line(
        build.GUILD_SITES[1],
        inputs,
        _summary_week({"Enhancing": 0}),
        None,
        draw_model.TrialDraw(skills=["Enhancing"], date="", min_levels={}),
    )
    assert f"seats {config.party_cap('li')} (FALLBACK constant" in line
    assert "invalid" in line
    assert "encampment L" not in line


# --- _fetch_guild, end to end: the cap each Buildings path produces ------------
def _stub_fetch_guild_for_cap(monkeypatch, scrape_buildings):
    """Stub every network call _fetch_guild makes; the Buildings tab is the test's."""
    from src import scraper

    gd = scraper.GuildData(
        tab="LI Member Data", fetched_at="t", member_count=1,
        members=[_member("Yedic", 100)],
    )
    monkeypatch.setattr(config, "ROSTER_SOURCE_ENABLED", False)
    monkeypatch.setattr(build, "scrape_member_tab", lambda tab: gd)
    monkeypatch.setattr(build.signup_model, "fetch_signup_csv", lambda tab: "csv")
    monkeypatch.setattr(
        build.draw_model, "trial_columns", lambda csv, tab: ["Foraging"]
    )
    monkeypatch.setattr(
        build.signup_model, "parse_signup", lambda csv, tab_label=None: {}
    )
    monkeypatch.setattr(build, "_fetch_combat", lambda site, csv: (None, "stub"))
    monkeypatch.setattr(build, "_fetch_building_value", lambda site: (None, "stub"))
    monkeypatch.setattr(
        build.buildings_model, "scrape_buildings_tab", scrape_buildings
    )


def _fetch_li():
    from src import draw as draw_model

    site = [s for s in build.GUILD_SITES if s.key == "li"][0]
    return build._fetch_guild(
        site, draw_model.TrialDraw(skills=["Foraging"], date="x")
    )


def test_fetch_guild_reads_the_cap_off_the_encampment(monkeypatch, capsys):
    _stub_fetch_guild_for_cap(monkeypatch, lambda tab, key: _observation(4))
    monkeypatch.setattr(config, "BUILDINGS_SOURCE_ENABLED", True)
    inputs = _fetch_li()
    assert inputs.party_cap.cap == 28
    assert inputs.party_cap.source == "encampment L4"
    assert "party cap" not in capsys.readouterr().err


def test_fetch_guild_with_the_buildings_flag_off_falls_back(monkeypatch, capsys):
    def never(tab, key):
        raise AssertionError("the flag is off: the tab must not be fetched")

    _stub_fetch_guild_for_cap(monkeypatch, never)
    monkeypatch.setattr(config, "BUILDINGS_SOURCE_ENABLED", False)
    inputs = _fetch_li()
    assert inputs.party_cap.cap == config.party_cap("li")
    assert inputs.party_cap.source.startswith("FALLBACK constant")
    assert "not read" in inputs.party_cap.source
    assert "BUILDINGS_SOURCE_ENABLED" in inputs.party_cap.source
    assert "WARNING (li)" in capsys.readouterr().err


def test_fetch_guild_with_an_unreadable_buildings_tab_falls_back(monkeypatch, capsys):
    from src.reader import SheetStructureError

    def boom(tab, key):
        raise SheetStructureError("header changed")

    _stub_fetch_guild_for_cap(monkeypatch, boom)
    monkeypatch.setattr(config, "BUILDINGS_SOURCE_ENABLED", True)
    inputs = _fetch_li()
    assert inputs.party_cap.cap == config.party_cap("li")
    assert inputs.party_cap.source.startswith("FALLBACK constant")
    assert "not read" in inputs.party_cap.source
    assert "unreadable" in inputs.party_cap.source
    assert "party cap" in capsys.readouterr().err


def test_fetch_guild_with_no_encampment_row_falls_back(monkeypatch, capsys):
    _stub_fetch_guild_for_cap(monkeypatch, lambda tab, key: _observation(None))
    monkeypatch.setattr(config, "BUILDINGS_SOURCE_ENABLED", True)
    inputs = _fetch_li()
    assert inputs.party_cap.cap == config.party_cap("li")
    assert "no Skilling Encampment row" in inputs.party_cap.source
    assert "no Skilling Encampment row" in capsys.readouterr().err


def test_fetch_guild_with_an_invalid_level_cell_falls_back(monkeypatch, capsys):
    """The parser reads a blank, garbled or negative cell as 0; so does this."""
    _stub_fetch_guild_for_cap(monkeypatch, lambda tab, key: _observation(0))
    monkeypatch.setattr(config, "BUILDINGS_SOURCE_ENABLED", True)
    inputs = _fetch_li()
    assert inputs.party_cap.cap == config.party_cap("li")
    assert inputs.party_cap.source.startswith("FALLBACK constant")
    assert "invalid" in inputs.party_cap.source
    assert "invalid" in capsys.readouterr().err


@pytest.mark.parametrize("module, name", [
    ("config", "FLEX_THRESHOLDS"),
    ("trials", "guild_shrine_upgrade_total_cost"),
    ("build", "_provenance_placeholder"),
    ("processor", "_serialize_member"),
])
def test_dead_code_stays_deleted(module, name):
    """Finding 18: unreferenced code removed; nothing in this tree or the sibling
    repos read it. Re-adding one is a decision, not a drift."""
    import importlib

    assert not hasattr(importlib.import_module(f"src.{module}"), name)
    from src import scraper

    assert not hasattr(scraper.GuildData, "to_dict")


def _restart_job(levels, level):
    """20 golden members, the golden draw, cap 8: small enough to be quick, tight
    enough that restarts land on DIFFERENT parties (restart 0 scores below the rest),
    so a restart run with the wrong seed or scope cannot pass by coincidence."""
    from tests.golden_fixture import GOLDEN_DRAW, golden_members

    return {**_job(levels, cap=8), "members": golden_members()[:20],
            "skills": list(GOLDEN_DRAW), "level": level}


def test_each_restart_job_reproduces_that_restart_of_the_units_ensemble(monkeypatch):
    """_compute_restart(i) must be EXACTLY restart i of the unit's own serial ensemble:
    same scorer inputs, same seed, same building and buff scopes."""
    from src import optimizer

    monkeypatch.setattr(config, "TRIALS_BUFF_LEVEL_SLIDER", False)
    for job in (_restart_job({"Milking": 3}, 5), _restart_job({}, None)):
        seen = []
        real = optimizer.run_restart

        def spy(scorer, i, seed):
            parties = real(scorer, i, seed)
            seen.append([set(p) for p in parties])  # later passes mutate in place
            return parties

        monkeypatch.setattr(optimizer, "run_restart", spy)
        build._compute_unit(job)
        monkeypatch.setattr(optimizer, "run_restart", real)
        assert len(seen) == len(config.OPT_ENSEMBLE_PIPELINES)
        assert len({str(p) for p in seen}) > 1, "restarts must differ to test anything"
        for i, parties in enumerate(seen):
            assert build._compute_restart({**job, "restart": i}) == parties


def test_restarts_split_across_processes_match_the_serial_ensemble(monkeypatch):
    """One pool job per (unit, restart) ships the SAME weeks as each unit running its
    own ensemble serially: same parties, same tie rule, same order."""
    jobs = [_restart_job({"Milking": 3}, 5), _restart_job({}, None)]
    monkeypatch.setattr(config, "BUILD_PARALLEL", False)
    serial = build._run_units(jobs)
    monkeypatch.setattr(config, "BUILD_PARALLEL", True)
    monkeypatch.setattr(config, "BUILD_MAX_WORKERS", 4)
    split = build._run_units(jobs)

    def plan(results):  # the clock is not the plan
        for r in results:
            for week in (r["week"], *r["ladder"].values()):
                week.pop("generated_at")
                week.pop("week_date")
        return results

    assert plan(split) == plan(serial)
