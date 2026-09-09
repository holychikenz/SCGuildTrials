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
