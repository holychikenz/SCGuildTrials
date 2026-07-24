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
