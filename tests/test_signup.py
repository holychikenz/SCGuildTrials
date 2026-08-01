"""Unit tests for the sign-up-aware planner (src/signup.py). No network access.

Covers the Trial Signup CSV parser (the four fixed skilling columns B–E, combat
columns after them ignored by position, the "User" wrong-tab guard, the
Alchemy = "Bell Farming" mapping, and the loud structural guards), and the
enforced plan's
invariants: volunteers are locked into their chosen trial and never benched,
open seats are filled only from the uncommitted pool and only where they do not
lower a party's tier, and the advisory swaps are strictly improving and
internally consistent.
"""

import pytest

from src import config, signup
from src.reader import MemberRow, SheetStructureError, SkillEntry


# ---------------------------------------------------------------------------
# Fast optimizer budget (the "enforced <= optimal" test computes a real optimum)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _fast_optimizer_budget(monkeypatch):
    monkeypatch.setattr(config, "OPT_SA_ITERS", 1000)
    monkeypatch.setattr(config, "OPT_SA_RESTARTS", 1)
    monkeypatch.setattr(config, "OPT_GA_POP", 16)
    monkeypatch.setattr(config, "OPT_GA_GENERATIONS", 15)
    monkeypatch.setattr(config, "OPT_BEAM_WIDTH", 5)
    monkeypatch.setattr(config, "OPT_HILLCLIMB_MAX_ITERS", 100)


# ---------------------------------------------------------------------------
# Fixtures (inline; nothing here touches Google Sheets)
# ---------------------------------------------------------------------------
def _member(name, levels=None):
    levels = levels or {}
    skills = {
        sk: SkillEntry(level=levels.get(sk, 100), tool=False, top=False, bot=False)
        for sk in config.SKILLS
    }
    return MemberRow(
        name=name, main_classes="", flex="", flex_levels=[], skills=skills
    )


# ---------------------------------------------------------------------------
# parse_signup
# ---------------------------------------------------------------------------
def _signup_csv(rows, columns=None, combat=("Hedgehog", "Jellyfish")):
    """Build a Trial Signup gviz-style CSV in the LIVE compact layout.

    ``columns`` is the ordered list of the FOUR skilling-trial header names
    (spreadsheet cols B–E); defaults to the first four ``config.SKILLS``.
    ``combat`` are the trailing combat columns (cols F+), which ``parse_signup``
    must ignore by position. Each row's ``ticked`` set names the columns (skilling
    OR combat) set TRUE, matched against the header names.
    """
    columns = list(columns if columns is not None else config.SKILLS[:4])
    all_cols = columns + list(combat)
    header = ["User"] + all_cols
    lines = [",".join(header)]
    for name, ticked in rows:
        cells = [name] + ["TRUE" if col in ticked else "FALSE" for col in all_cols]
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


def test_parse_signup_reads_fixed_skilling_columns():
    csv_text = _signup_csv(
        [
            ("Alice", {"Foraging"}),
            ("Bob", {"Woodcutting"}),
            ("Cara", set()),
        ],
        columns=["Milking", "Foraging", "Woodcutting", "C.Smithing"],
    )
    picks = signup.parse_signup(csv_text)
    assert picks == {
        "Alice": {"Foraging"},
        "Bob": {"Woodcutting"},
        "Cara": set(),
    }


def test_parse_signup_alchemy_is_bell_farming_column():
    # The "Alchemy" skilling column resolves to the sheet's "Bell Farming" name.
    csv_text = _signup_csv(
        [("Al", {"Alchemy"})],
        columns=["Woodcutting", "Crafting", "Alchemy", "Milking"],
    )
    picks = signup.parse_signup(csv_text)
    assert picks["Al"] == {"Bell Farming"}
    # And the planner maps the Alchemy trial onto that column.
    assert signup._sheet_column_for("Alchemy") == "Bell Farming"
    assert signup._locked_skill_of({"Bell Farming"}, ["Alchemy"]) == "Alchemy"


def test_parse_signup_cheesesmithing_alias():
    # The game's "Cheesesmithing" label resolves to the "C.Smithing" sheet column.
    csv_text = _signup_csv(
        [("Al", {"Cheesesmithing"})],
        columns=["Cheesesmithing", "Foraging", "Woodcutting", "Milking"],
    )
    assert signup.parse_signup(csv_text)["Al"] == {"C.Smithing"}


def test_parse_signup_live_layout_with_aliases_and_combat():
    # The live compact layout: User, four skilling trials in cols B–E (NOT in
    # draw order), then two combat columns (cols F–G) that MUST be ignored by
    # position. "Alchemy" resolves to the "Bell Farming" sheet column.
    csv_text = (
        "User,Woodcutting,Crafting,Alchemy,Milking,Hedgehog,Jellyfish\n"
        "Alice,FALSE,TRUE,FALSE,FALSE,TRUE,FALSE\n"
        "Bob,FALSE,FALSE,TRUE,FALSE,FALSE,TRUE\n"
        "Cara,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE\n"
    )
    picks = signup.parse_signup(csv_text)
    assert picks == {
        "Alice": {"Crafting"},        # combat "Hedgehog" tick ignored
        "Bob": {"Bell Farming"},      # "Alchemy" header -> Bell Farming column
        "Cara": {"Woodcutting"},
    }


def test_parse_signup_ignores_columns_after_the_skilling_block():
    # Anything from column F (index 5) on is combat/extra and ignored — even a
    # tick. Only the four fixed skilling columns (B–E) count.
    csv_text = _signup_csv(
        [("Alice", {"Milking", "Hedgehog", "Jellyfish"})],
        columns=["Milking", "Foraging", "Woodcutting", "C.Smithing"],
        combat=("Hedgehog", "Jellyfish"),
    )
    picks = signup.parse_signup(csv_text)
    assert picks["Alice"] == {"Milking"}  # both combat ticks dropped


def test_parse_signup_requires_four_skilling_columns():
    # Fewer than User + 4 skilling columns -> loud structural failure (a shrunk
    # or wrong tab), rather than silently reading a truncated block.
    bad = "User,Milking,Foraging\nAlice,TRUE,FALSE\n"
    with pytest.raises(SheetStructureError):
        signup.parse_signup(bad)


def test_parse_signup_rejects_unknown_skilling_header():
    # A non-skill header INSIDE the fixed skilling block (B–E) means a layout
    # change or the wrong tab -> fail loudly rather than silently mis-seat.
    bad = (
        "User,Milking,Badger,Woodcutting,Crafting,Hedgehog\n"
        "Alice,TRUE,FALSE,FALSE,FALSE,FALSE\n"
    )
    with pytest.raises(SheetStructureError):
        signup.parse_signup(bad)


def test_parse_signup_stops_at_blank_user():
    csv_text = _signup_csv(
        [("Alice", {"Foraging"})],
        columns=["Milking", "Foraging", "Woodcutting", "C.Smithing"],
    )
    # A blank-User row ends the table; the ghost after it is never read.
    csv_text += ",FALSE,FALSE,FALSE,FALSE,FALSE,FALSE\nGhost,TRUE,TRUE,TRUE,TRUE\n"
    picks = signup.parse_signup(csv_text)
    assert "Alice" in picks and "Ghost" not in picks


def test_parse_signup_guards_wrong_tab():
    # gviz silently serves a different tab; a header without "User" must fail.
    bad = "Member,Main Classes,Flex\nAlice,,\n"
    with pytest.raises(SheetStructureError):
        signup.parse_signup(bad)


# ---------------------------------------------------------------------------
# plan — enforced invariants
# ---------------------------------------------------------------------------
def _scenario():
    """Two-trial scenario with strong volunteers, a strong non-signup, and a
    weak non-signup that should never help."""
    draw = ["Foraging", "Woodcutting"]
    members = [
        _member("F1", {"Foraging": 150}),
        _member("F2", {"Foraging": 150}),
        _member("F3", {"Foraging": 150}),
        _member("W1", {"Woodcutting": 150}),
        _member("W2", {"Woodcutting": 150}),
        _member("StrongN", {"Woodcutting": 150, "Foraging": 150}),
        _member("WeakN", {sk: 20 for sk in config.SKILLS}),
    ]
    picks = {
        "F1": {"Foraging"}, "F2": {"Foraging"}, "F3": {"Foraging"},
        "W1": {"Woodcutting"}, "W2": {"Woodcutting"},
        "StrongN": set(), "WeakN": set(),
    }
    return members, picks, draw


def _plan(members, picks, draw, cap=3):
    # optimal inputs are display-only for these structural checks.
    return signup.plan(
        members, picks, optimal_total=9999, optimal_summary=[], draw=draw, cap=cap
    )


def test_volunteers_are_locked_and_never_benched():
    members, picks, draw = _scenario()
    p = _plan(members, picks, draw)

    placed = {}  # name -> skill
    for t in p.trials:
        for r in t.roster:
            if r.status == "assigned":
                placed[r.name] = t.skill
    # Every volunteer appears, in exactly the trial they ticked, as "assigned".
    assert placed == {
        "F1": "Foraging", "F2": "Foraging", "F3": "Foraging",
        "W1": "Woodcutting", "W2": "Woodcutting",
    }
    # No volunteer is on the bench.
    assert "F1" not in p.enforced_bench and "W1" not in p.enforced_bench


def test_fills_come_only_from_non_signups():
    members, picks, draw = _scenario()
    p = _plan(members, picks, draw)
    non_signups = {"StrongN", "WeakN"}
    for t in p.trials:
        for r in t.roster:
            if r.status == "recommended":
                assert r.name in non_signups


def test_cap_respected_and_bench_is_non_signups():
    members, picks, draw = _scenario()
    p = _plan(members, picks, draw, cap=3)
    for t in p.trials:
        assert t.party_size <= 3
    assert set(p.enforced_bench) <= {"StrongN", "WeakN"}


def test_weak_fill_that_lowers_points_is_not_seated():
    # WeakN (level 20) should never be seated where it lowers a party's tier;
    # StrongN should be preferred for the one open Woodcutting seat.
    members, picks, draw = _scenario()
    p = _plan(members, picks, draw, cap=3)
    wc = next(t for t in p.trials if t.skill == "Woodcutting")
    fills = [r.name for r in wc.roster if r.status == "recommended"]
    assert "StrongN" in fills
    # Any seated fill must have gain >= 0 (never lowers points).
    for t in p.trials:
        for r in t.roster:
            if r.status == "recommended":
                assert r.fill_gain is not None and r.fill_gain >= 0


def test_swaps_are_strictly_improving_and_consistent():
    members, picks, draw = _scenario()
    p = _plan(members, picks, draw)
    for s in p.swaps:
        assert s.gain > 0
        assert s.action in ("recruit", "bench", "move", "swap", "reshuffle")
        # A reshuffle carries its component swaps; a single move never does.
        if s.action == "reshuffle":
            assert s.moves and all(
                {"in", "out", "from_skill"} <= set(m) for m in s.moves
            )
        else:
            assert not s.moves
    assert p.reachable_total == p.enforced_total + sum(s.gain for s in p.swaps)
    assert p.reachable_total >= p.enforced_total


def test_compound_reshuffle_crosses_a_tier_plateau():
    """A stalled single-move climb still closes a tier gap via a grouped reshuffle.

    Points are a STEP function of tier, so it is normal for NO single swap to
    change the score even when the party is one tier short — a strict single-move
    climb then recommends nothing. This models that exactly: skill A crosses to
    the higher tier only once its combined strength reaches 30, which needs TWO
    swaps (each individually worth 0). The engine must record the pair as one
    strictly-positive ``reshuffle`` and reach the optimal ceiling.
    """
    import types

    from src import signup as signup_mod

    draw = ["A", "B"]
    # A-strength per member index; B's score ignores composition (donor trial).
    str_a = {0: 9, 1: 8, 2: 8, 3: 12, 4: 11, 5: 10}
    members = [types.SimpleNamespace(name=f"m{i}") for i in range(6)]

    class FakeScorer:
        skills = draw
        def __init__(self):
            self.members = members
        def party_points(self, s, ids):
            if self.skills[s] == "A":
                return 200 if sum(str_a[i] for i in ids) >= 30 else 100
            return 100  # skill B: fixed, so donor swaps never regress
        def total_points(self, parties):
            return sum(self.party_points(s, parties[s]) for s in range(len(parties)))

    scorer = FakeScorer()
    # φ (progress potential) reads member A-strength; tier arg is irrelevant here.
    monkey = pytest.MonkeyPatch()
    monkey.setattr(signup_mod, "rate", lambda m, skill, tier: str_a[int(m.name[1:])] if skill == "A" else 0.0)
    try:
        enforced = [{0, 1, 2}, {3, 4, 5}]  # A = 25 (< 30) -> 100 pts; total 200
        assert scorer.total_points(enforced) == 200
        swaps, reachable = signup_mod._improving_swaps(
            enforced, scorer, cap=3, draw=draw, members=members,
            optimal_points={"A": 200, "B": 100}, optimal_tier={"A": 5, "B": 5},
        )
    finally:
        monkey.undo()

    assert reachable == 300  # crossed to A's higher tier
    assert reachable == 200 + sum(s.gain for s in swaps)
    assert all(s.gain > 0 for s in swaps)
    reshuffles = [s for s in swaps if s.action == "reshuffle"]
    assert len(reshuffles) == 1
    grp = reshuffles[0]
    assert grp.gain == 100 and grp.to_skill == "A"
    assert len(grp.moves) == 2  # two individually-break-even swaps, one crossing


def test_plan_is_deterministic():
    members, picks, draw = _scenario()
    a = _plan(members, picks, draw).to_dict()
    b = _plan(members, picks, draw).to_dict()
    for k in ("generated_at", "week_date"):
        a.pop(k), b.pop(k)
    assert a == b


def test_enforced_never_exceeds_real_optimum():
    from src.optimizer import optimize
    from src.trials import simulate_race

    members, picks, draw = _scenario()
    cap = 3
    opt = optimize(members, draw, cap=cap, strategy="best")
    optimal_total = sum(
        simulate_race(opt.parties[s], s).points for s in draw
    )
    p = signup.plan(
        members, picks, optimal_total=optimal_total,
        optimal_summary=[], draw=draw, cap=cap,
    )
    # The enforced plan is a feasible (constrained) assignment; the optimum is
    # the unconstrained max, so enforced can never beat it — and the improving
    # swaps must stay within the ceiling.
    assert p.enforced_total <= optimal_total
    assert p.reachable_total <= optimal_total


# ---------------------------------------------------------------------------
# Reported time margin (how "safe" the shipped lineup is)
# ---------------------------------------------------------------------------
def test_trial_margin_matches_a_fresh_simulation_of_the_shipped_roster():
    # The page's safety numbers must describe the roster it actually shows, so
    # re-simulate each trial's rendered party and expect the same margin back.
    from src.trials import simulate_race, tier_clear_seconds, time_slack_fraction

    members, picks, draw = _scenario()
    by_name = {m.name: m for m in members}
    p = _plan(members, picks, draw)

    for t in p.trials:
        party = [by_name[r.name] for r in t.roster]
        result = simulate_race(party, t.skill, p.target_scale)
        assert t.clear_seconds == tier_clear_seconds(result)
        assert t.slack_fraction == time_slack_fraction(result)
        # The two forms are the same fact: seconds banked, and budget left over.
        if t.clear_seconds is not None:
            assert t.slack_fraction == pytest.approx(
                1.0 - t.clear_seconds / config.TRIAL_TIME_BUDGET_SECONDS
            )
            assert 0.0 <= t.slack_fraction < 1.0


def test_trial_that_banks_no_tier_reports_no_margin_and_is_left_out_of_the_min():
    # A party too weak to clear tier 1 has banked nothing, so it has no margin to
    # report — and must not drag the "thinnest margin" headline to 0%, which would
    # read as "we are one second from losing a tier" when the truth is "that trial
    # scores nothing at all". The two failures need different fixes, so the page
    # must not conflate them.
    draw = ["Foraging", "Woodcutting"]
    members = [
        _member("Strong", {"Foraging": 200}),
        _member("Feeble", {sk: 1 for sk in config.SKILLS}),
    ]
    picks = {"Strong": {"Foraging"}, "Feeble": {"Woodcutting"}}
    p = signup.plan(
        members, picks, optimal_total=0, optimal_summary=[], draw=draw, cap=1
    )

    forg = next(t for t in p.trials if t.skill == "Foraging")
    wood = next(t for t in p.trials if t.skill == "Woodcutting")
    assert forg.tier_reached >= 1 and forg.clear_seconds is not None
    assert wood.tier_reached == 0
    assert wood.clear_seconds is None and wood.slack_fraction == 0.0
    # Only the trial that banked a tier sets the headline margin.
    assert p.min_slack_fraction == forg.slack_fraction


def test_min_slack_is_none_when_nothing_banks_a_tier():
    draw = ["Foraging"]
    members = [_member("Feeble", {sk: 1 for sk in config.SKILLS})]
    p = signup.plan(
        members, {"Feeble": {"Foraging"}}, optimal_total=0,
        optimal_summary=[], draw=draw, cap=1,
    )
    assert p.trials[0].tier_reached == 0
    assert p.min_slack_fraction is None


def test_slack_band_colours_by_the_config_thresholds():
    from src import build

    assert build._slack_band(None) == "danger-text"          # nothing banked
    assert build._slack_band(0.0) == "danger-text"           # held by a hair
    assert build._slack_band(config.SLACK_THIN - 1e-9) == "danger-text"
    assert build._slack_band(config.SLACK_THIN) == "warn-text"
    assert build._slack_band(config.SLACK_OK - 1e-9) == "warn-text"
    assert build._slack_band(config.SLACK_OK) == "ok-text"
    assert build._slack_band(0.9) == "ok-text"


def test_signup_html_reports_the_margin_per_trial_and_in_the_strip():
    from src import build

    members, picks, draw = _scenario()
    site = build.GUILD_SITES[0]
    plan_dict = _plan(members, picks, draw).to_dict()
    page = build._render_signup_html(plan_dict, site)

    assert "Thinnest margin" in page
    # Every trial that banked a tier states when it banked it, out of the budget.
    banked = [t for t in plan_dict["trials"] if t["tier_reached"] >= 1]
    assert banked, "fixture should bank at least one tier"
    assert page.count("banked at") >= len(banked)
    for t in banked:
        assert f"{t['clear_seconds']:,.0f}s of 3,600s" in page


def test_points_equal_ceiling_still_warns_when_a_trial_is_on_the_buzzer():
    # The swap list only knows about points, so a plan that ties the ceiling used to
    # render as "nothing to change" even with a tier hanging on seconds. Live on SC
    # (2026-07-31) that was exactly the case: 4900 = ceiling, Foraging holding tier
    # 12 by 65 seconds. The page must not read as all-clear.
    from src import build

    members, picks, draw = _scenario()
    site = build.GUILD_SITES[0]
    base = _plan(members, picks, draw).to_dict()
    base["optimal_total"] = base["enforced_total"]
    base["reachable_total"] = base["enforced_total"]
    base["swaps"] = []
    base["optimal_summary"] = [
        {"skill": t["skill"], "party_size": t["party_size"],
         "tier_reached": t["tier_reached"], "points": t["points"],
         "clear_seconds": 0.20 * 3600, "slack_fraction": 0.80}
        for t in base["trials"]
    ]

    def _flat(page: str) -> str:
        """Collapse the rendered whitespace so wrapped prose can be matched."""
        return " ".join(page.split())

    # Knife-edge: one trial banks its tier with 1% of the hour to spare.
    thin = dict(base, trials=[dict(t) for t in base["trials"]])
    thin["trials"][0]["slack_fraction"] = 0.01
    thin["trials"][0]["clear_seconds"] = 0.99 * 3600
    page = _flat(build._render_signup_html(thin, site))
    assert "is not the same as being safe" in page
    assert "with only 1.0% of the hour spare" in page
    assert "against 80.0% for the unconstrained optimum" in page
    assert "Nothing to change" not in page

    # Comfortable everywhere: no caveat, and the points statement stands alone.
    safe = dict(base, trials=[dict(t) for t in base["trials"]])
    for t in safe["trials"]:
        t["slack_fraction"] = 0.40
        t["clear_seconds"] = 0.60 * 3600
    assert "is not the same as being safe" not in _flat(
        build._render_signup_html(safe, site)
    )


# ---------------------------------------------------------------------------
# Safety swaps (_safety_swaps): margin-only advisory moves
# ---------------------------------------------------------------------------
def _thin_scenario():
    """A draw whose Foraging trial banks its tier with 0.63% of the hour to spare.

    The levels were FOUND BY SEARCH, not guessed, to reproduce the live shape (LI,
    2026-07-31): an uncommitted member helps once, phase 1 then runs dry, and only a
    volunteer swap lifts Foraging the rest of the way. A fixture where one phase does
    all the work would leave the phase-ordering test asserting nothing.

    Foraging's volunteers are deliberately mediocre (122) beside Woodcutting's strong
    pair, and the two trials are balanced so the points stay equal across the swap —
    were they not, the pass would (correctly) refuse it and prove nothing here.
    """
    draw = ["Foraging", "Woodcutting"]
    members = [
        _member("Vol1", {"Foraging": 122}),
        _member("Vol2", {"Foraging": 122}),
        _member("Vol3", {"Woodcutting": 150, "Foraging": 150}),
        _member("Vol4", {"Woodcutting": 150, "Foraging": 148}),
        _member("Vol5", {"Woodcutting": 150}),
        _member("FreeA", {"Foraging": 130, "Woodcutting": 130}),
        _member("FreeB", {"Foraging": 122, "Woodcutting": 136}),
        _member("FreeWeak", {sk: 40 for sk in config.SKILLS}),
    ]
    picks = {
        "Vol1": {"Foraging"}, "Vol2": {"Foraging"},
        "Vol3": {"Woodcutting"}, "Vol4": {"Woodcutting"}, "Vol5": {"Woodcutting"},
    }
    return members, picks, draw


def _run_safety(members, picks, draw, cap=4, **kw):
    """Build the enforced plan, then run the safety pass over it directly."""
    from src.optimizer import AssignmentScorer

    p = signup.plan(
        members, picks, optimal_total=0, optimal_summary=[], draw=draw, cap=cap
    )
    name_to_idx = {m.name: i for i, m in enumerate(members)}
    parties = [
        {name_to_idx[r.name] for r in t.roster} for t in p.trials
    ]
    free_pool = {name_to_idx[n] for n in p.non_signups}
    scorer = AssignmentScorer(members, draw, p.target_scale, cap)
    return p, scorer, parties, signup._safety_swaps(
        parties, scorer, cap, draw, members, free_pool, **kw
    )


def test_safety_swaps_never_change_the_points():
    # The card is captioned "same points, more margin"; that must be a guarantee, not
    # an aspiration. A live probe (2026-07-31) initially produced a move that GAINED
    # a tier on LI while crashing that trial's margin 25.96% -> 0.23% — a points win
    # smuggled into a safety list. Points gains belong to the points swaps.
    members, picks, draw = _thin_scenario()
    p, scorer, parties, (moves, _after) = _run_safety(members, picks, draw)

    before = scorer.total_points(parties)
    replay = [set(q) for q in parties]
    name_to_idx = {m.name: i for i, m in enumerate(members)}
    for mv in moves:
        s_from = draw.index(mv.from_skill) if mv.from_skill else -1
        s_to = draw.index(mv.to_skill) if mv.to_skill else -1
        if mv.action == "swap":
            a, b = s_from, s_to
            m1, m2 = name_to_idx[mv.member], name_to_idx[mv.partner]
            replay[a].discard(m1); replay[a].add(m2)
            replay[b].discard(m2); replay[b].add(m1)
        else:
            m = name_to_idx[mv.member]
            if s_from >= 0:
                replay[s_from].discard(m)
            if s_to >= 0:
                replay[s_to].add(m)
        # Every prefix of the list is a valid plan worth the same points, which is
        # what lets the page tell officers to apply as many as they like, in order.
        assert scorer.total_points(replay) == before


def test_safety_swaps_each_strictly_raise_the_thinnest_margin():
    # Ranking on (points, min, sum) alone lets a move through on `sum` while the
    # thinnest trial stays put: on SC that produced five moves, all leaving Foraging
    # at 1.81% — advice that fixed nothing. Each entry must earn its place.
    members, picks, draw = _thin_scenario()
    _p, _scorer, _parties, (moves, _after) = _run_safety(members, picks, draw)
    for mv in moves:
        assert mv.min_after > mv.min_before, mv.note
    # The list is a ladder: each move's "after" is the next one's "before".
    for prev, nxt in zip(moves, moves[1:]):
        assert nxt.min_before == prev.min_after


def test_safety_swaps_report_the_margin_they_end_on():
    members, picks, draw = _thin_scenario()
    _p, _scorer, _parties, (moves, after) = _run_safety(members, picks, draw)
    if moves:
        assert after == pytest.approx(moves[-1].min_after)


def test_safety_swaps_stop_once_the_lineup_is_comfortable():
    # The pass exists to get off the buzzer, not to gold-plate: a target of 0 means
    # "already comfortable", so it must propose nothing at all.
    members, picks, draw = _thin_scenario()
    _p, _scorer, _parties, (moves, _after) = _run_safety(
        members, picks, draw, target=0.0
    )
    assert moves == []


def test_safety_swaps_respect_the_move_limit():
    members, picks, draw = _thin_scenario()
    _p, _scorer, _parties, (moves, _after) = _run_safety(
        members, picks, draw, target=1.0, max_moves=2  # target 1.0 = never satisfied
    )
    assert len(moves) <= 2


def test_safety_swaps_exhaust_the_free_pool_before_overriding_a_signup():
    # Phase 1 (uncommitted members only) is played out in full before any volunteer is
    # questioned, so the override-free run is exactly the leading stretch of the full
    # one. NB the flags are NOT sorted in general: phase 2's pool is a SUPERSET, so a
    # free-pool move can legitimately follow an override once the plan has changed
    # under it — asserting False-then-True would be asserting a falsehood.
    members, picks, draw = _thin_scenario()
    _p, _s, _parties, (full, _a) = _run_safety(members, picks, draw, target=1.0)
    _p, _s, _parties, (free_only, _b) = _run_safety(
        members, picks, draw, target=1.0, allow_overrides=False
    )

    assert not any(m.overrides_signup for m in free_only)
    assert [m.note for m in full[: len(free_only)]] == [m.note for m in free_only]
    # The fixture must actually exercise BOTH phases, or the prefix check above is
    # comparing two empty lists and the test proves nothing.
    assert len(free_only) >= 1
    assert any(m.overrides_signup for m in full)
    assert len(full) > len(free_only)


def test_safety_overrides_can_be_switched_off_entirely():
    members, picks, draw = _thin_scenario()
    _p, _s, _parties, (moves, _after) = _run_safety(
        members, picks, draw, target=1.0, allow_overrides=False
    )
    for mv in moves:
        assert not mv.overrides_signup


def test_safety_swaps_leave_the_shipped_plan_untouched():
    # The list is advisory: the rosters the page shows must be the enforced plan, not
    # a silently improved one.
    members, picks, draw = _thin_scenario()
    _p, _scorer, parties, _ = _run_safety(members, picks, draw, target=1.0)
    before = [set(q) for q in parties]
    signup._safety_swaps(
        parties, _scorer, 4, draw, members,
        {i for i, m in enumerate(members) if m.name.startswith("Free")},
        target=1.0,
    )
    assert parties == before


def test_plan_exposes_safety_swaps_and_is_still_deterministic():
    members, picks, draw = _thin_scenario()
    a = signup.plan(
        members, picks, optimal_total=0, optimal_summary=[], draw=draw, cap=4
    ).to_dict()
    b = signup.plan(
        members, picks, optimal_total=0, optimal_summary=[], draw=draw, cap=4
    ).to_dict()
    for k in ("generated_at", "week_date"):
        a.pop(k), b.pop(k)
    assert a == b
    assert "safety_swaps" in a and "safety_min_slack" in a
    # The safety pass can only improve on what ships (or leave it alone).
    if a["min_slack_fraction"] is not None:
        assert a["safety_min_slack"] >= a["min_slack_fraction"]


def test_safety_section_renders_the_ladder_and_flags_overrides():
    from src import build

    members, picks, draw = _thin_scenario()
    site = build.GUILD_SITES[0]
    p = signup.plan(
        members, picks, optimal_total=0, optimal_summary=[], draw=draw, cap=4
    ).to_dict()
    page = " ".join(build._render_signup_html(p, site).split())
    assert "Safety swaps" in page

    # A hand-built pair of moves, one of which overrides a sign-up, must render both
    # the margin ladder and the override flag.
    doctored = dict(p)
    doctored["min_slack_fraction"] = 0.02
    doctored["safety_min_slack"] = 0.17
    doctored["safety_min_probability"] = 0.97
    doctored["safety_swaps"] = [
        {"member": "FreeMid", "action": "move", "from_skill": "Foraging",
         "to_skill": "Woodcutting", "note": "Move FreeMid.", "partner": None,
         "min_before": 0.02, "min_after": 0.09, "overrides_signup": False,
         "min_prob_before": 0.61, "min_prob_after": 0.88,
         "trial_changes": [{"skill": "Foraging", "before": 0.02, "after": 0.09,
                            "prob_before": 0.61, "prob_after": 0.88}]},
        {"member": "Vol1", "action": "swap", "from_skill": "Foraging",
         "to_skill": "Woodcutting", "note": "Swap Vol1 with Vol3.", "partner": "Vol3",
         "min_before": 0.09, "min_after": 0.17, "overrides_signup": True,
         "min_prob_before": 0.88, "min_prob_after": 0.97,
         "trial_changes": []},
    ]
    page = " ".join(build._render_signup_html(doctored, site).split())
    # Reported in odds, with the margin retained beside it — the reader needs both:
    # a probability alone cannot say whether it was bought with seconds or minutes.
    assert "These 2 move(s) take the weakest trial from" in page
    assert "97%" in page and "likely to hold" in page
    assert "2.0%" in page and "17.0%" in page
    assert "overrides sign-up" in page
    # The per-move ladder rungs, in both currencies.
    assert "61%" in page and "88%" in page

    # The closing verdict leads on ODDS, not on the margin target. At 97% the ladder
    # has cleared the 15% margin the pass aims for but has NOT reached comfortable, and
    # the page must not claim otherwise — announcing "comfortable" over a 1-in-33 chance
    # of dropping a tier is exactly the overstatement the probability was added to stop.
    assert "at the 15.0% margin the pass aims for" in page
    assert "comfortable." not in page

    comfortable = dict(doctored, safety_min_probability=0.995)
    comfortable["safety_swaps"] = [
        dict(doctored["safety_swaps"][0]),
        dict(doctored["safety_swaps"][1], min_prob_after=0.995),
    ]
    page = " ".join(build._render_signup_html(comfortable, site).split())
    assert "comfortable." in page


def test_safety_swaps_carry_probabilities_alongside_the_margins():
    """The ladder is REPORTED in odds but SELECTED on margin — both must be present.

    The rendering test above hand-feeds its swap dicts, so it cannot catch
    signup.plan failing to populate the probability fields at all. This checks the
    real pipeline, and pins the invariant that matters: probability moves in the
    SAME direction as the margin the search actually optimised. If those two ever
    disagreed on an accepted move, the page would be recommending a swap on one
    currency while displaying another.
    """
    members, picks, draw = _thin_scenario()
    p = signup.plan(
        members, picks, optimal_total=0, optimal_summary=[], draw=draw, cap=4
    ).to_dict()

    assert "safety_min_probability" in p
    for m in p["safety_swaps"]:
        assert m["min_prob_before"] is not None
        assert m["min_prob_after"] is not None
        # Every accepted move strictly raises the thinnest margin (by construction),
        # so it must not LOWER the weakest trial's odds.
        assert m["min_after"] > m["min_before"]
        assert m["min_prob_after"] >= m["min_prob_before"] - 1e-9
        for c in m["trial_changes"]:
            assert c["prob_before"] is not None and c["prob_after"] is not None
            # Within a single trial the map from margin to probability is strictly
            # monotone, so the two must agree on the direction of travel.
            assert (c["after"] > c["before"]) == (c["prob_after"] > c["prob_before"])

    # The ladder's endpoint is what the summary tile promises.
    if p["safety_swaps"]:
        assert p["safety_min_probability"] == p["safety_swaps"][-1]["min_prob_after"]


def test_safety_section_says_so_when_nothing_helps():
    from src import build

    members, picks, draw = _thin_scenario()
    site = build.GUILD_SITES[0]
    base = signup.plan(
        members, picks, optimal_total=0, optimal_summary=[], draw=draw, cap=4
    ).to_dict()

    # Thin, but no move found: the page must NOT imply the risk is fixable.
    stuck = dict(base, safety_swaps=[], min_slack_fraction=0.02, safety_min_slack=0.02)
    page = " ".join(build._render_signup_html(stuck, site).split())
    assert "None found" in page and "would cost points" in page

    # Comfortable: reassure, do not invent work.
    fine = dict(base, safety_swaps=[], min_slack_fraction=0.40, safety_min_slack=0.40)
    page = " ".join(build._render_signup_html(fine, site).split())
    assert "None needed" in page


def test_optimal_summary_carries_the_optimums_own_margin():
    # The comparison table shows what the safety pass achieves on the
    # unconstrained optimum, which is the standard the sign-up plan is read
    # against. Without it the page can say "you are 300 points short" but not
    # "and the assignment you could have had was far safer".
    from src.trials import run_week

    members, _picks, draw = _scenario()
    week = run_week(members, skills=draw, cap=3)
    total, summary = signup.optimal_from_week(week)

    assert total == week.total_points
    for o, t in zip(summary, week.trials):
        assert o["skill"] == t.skill
        assert ("clear_seconds" in o) and ("slack_fraction" in o)
        if t.tier_reached >= 1:
            assert o["clear_seconds"] is not None
            assert 0.0 <= o["slack_fraction"] < 1.0
        else:
            assert o["clear_seconds"] is None and o["slack_fraction"] == 0.0


def test_signup_matches_member_name_case_insensitively():
    # The sign-up "User" cell is the raw in-game name; the member tab is
    # hand-maintained and here disagrees only by capitalisation. The volunteer
    # must still be locked in, and the fix-up reported in ``normalized_matches``.
    draw = ["Foraging", "Woodcutting"]
    members = [_member("dome", {"Foraging": 150})]  # member-tab casing
    picks = {"Dome": {"Foraging"}}                   # sign-up (in-game) casing
    p = signup.plan(
        members, picks, optimal_total=0, optimal_summary=[], draw=draw, cap=3
    )
    forg = next(t for t in p.trials if t.skill == "Foraging")
    assert any(r.name == "dome" and r.status == "assigned" for r in forg.roster)
    assert p.signup_count == 1
    assert p.unmatched_signups == []
    assert p.normalized_matches == ["Dome ≈ dome"]


def test_signup_unmatched_names_are_collected_and_ignored():
    # A sign-up matching NO member is dropped (as before) but now REPORTED.
    draw = ["Foraging", "Woodcutting"]
    members = [_member("Real", {"Foraging": 150})]
    picks = {"Real": {"Foraging"}, "Ghost": {"Woodcutting"}}
    p = signup.plan(
        members, picks, optimal_total=0, optimal_summary=[], draw=draw, cap=3
    )
    assert p.unmatched_signups == ["Ghost"]
    names = {r.name for t in p.trials for r in t.roster}
    assert "Ghost" not in names


def test_ambiguous_normalized_name_is_matched_exactly_only():
    # Two members that differ only by case make the normalised key ambiguous;
    # a third-casing sign-up must NOT be force-merged into either — it is
    # matched exactly only, and otherwise reported as unmatched.
    draw = ["Foraging", "Woodcutting"]
    members = [
        _member("AB", {"Foraging": 150}),
        _member("ab", {"Woodcutting": 150}),
    ]
    picks = {"AB": {"Foraging"}, "Ab": {"Woodcutting"}}
    p = signup.plan(
        members, picks, optimal_total=0, optimal_summary=[], draw=draw, cap=3
    )
    assert p.unmatched_signups == ["Ab"]      # ambiguous key -> not merged
    assert p.normalized_matches == []
    forg = next(t for t in p.trials if t.skill == "Foraging")
    assert any(r.name == "AB" and r.status == "assigned" for r in forg.roster)


def test_signup_html_flags_missing_players_in_red():
    # A sign-up with no member row must be surfaced in the red "missing-data"
    # card so officers can see who still needs to enter their data; when every
    # sign-up matches a member the card is absent.
    from src import build

    draw = ["Foraging", "Woodcutting"]
    members = [_member("Real", {"Foraging": 150})]
    site = build.GUILD_SITES[0]  # any real GuildSite (provides the tab names)

    with_missing = signup.plan(
        members, {"Real": {"Foraging"}, "Ghosty": {"Woodcutting"}},
        optimal_total=0, optimal_summary=[], draw=draw, cap=3,
    ).to_dict()
    html_text = build._render_signup_html(with_missing, site)
    assert 'id="missing-data"' in html_text
    assert "Ghosty" in html_text
    assert "missing data" in html_text  # header count

    none_missing = signup.plan(
        members, {"Real": {"Foraging"}},
        optimal_total=0, optimal_summary=[], draw=draw, cap=3,
    ).to_dict()
    assert 'id="missing-data"' not in build._render_signup_html(none_missing, site)


def test_signup_conflict_is_recorded_and_resolved_to_first_choice():
    draw = ["Foraging", "Woodcutting"]
    members = [_member("Dupe", {"Foraging": 150, "Woodcutting": 150})]
    picks = {"Dupe": {"Foraging", "Woodcutting"}}
    p = signup.plan(
        members, picks, optimal_total=0, optimal_summary=[], draw=draw, cap=3
    )
    assert len(p.conflicts) == 1 and "Dupe" in p.conflicts[0]
    # Locked into the first drawn choice (Foraging).
    forg = next(t for t in p.trials if t.skill == "Foraging")
    assert any(r.name == "Dupe" and r.status == "assigned" for r in forg.roster)
