"""Unit tests for the sign-up-aware planner (src/signup.py). No network access.

Covers the Trial Signup CSV parser (positional skill columns, the "User"
wrong-tab guard, the Alchemy = "Bell Farming" mapping), and the enforced plan's
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
def _signup_csv(rows):
    """Build a Trial Signup gviz-style CSV: header 'User' + booleans per skill."""
    header = ["User"] + [""] * len(config.SKILLS)
    lines = [",".join(header)]
    for name, ticked in rows:
        cells = [name] + [
            "TRUE" if sk in ticked else "FALSE" for sk in config.SKILLS
        ]
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


def test_parse_signup_reads_positional_columns():
    csv_text = _signup_csv(
        [
            ("Alice", {"Foraging"}),
            ("Bob", {"Woodcutting", "Enhancing"}),
            ("Cara", set()),
        ]
    )
    picks = signup.parse_signup(csv_text)
    assert picks == {
        "Alice": {"Foraging"},
        "Bob": {"Woodcutting", "Enhancing"},
        "Cara": set(),
    }


def test_parse_signup_alchemy_is_bell_farming_column():
    # The 9th skill column is "Bell Farming" = the Alchemy trial.
    csv_text = _signup_csv([("Al", {"Bell Farming"})])
    picks = signup.parse_signup(csv_text)
    assert picks["Al"] == {"Bell Farming"}
    # And the planner maps the Alchemy trial onto that column.
    assert signup._sheet_column_for("Alchemy") == "Bell Farming"
    assert signup._locked_skill_of({"Bell Farming"}, ["Alchemy"]) == "Alchemy"


def test_parse_signup_stops_at_blank_user():
    csv_text = _signup_csv([("Alice", {"Foraging"})])
    csv_text += "\n,FALSE\nGhost,TRUE\n"  # blank User row ends the table
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
        assert s.action in ("recruit", "bench", "move", "swap")
    assert p.reachable_total == p.enforced_total + sum(s.gain for s in p.swaps)
    assert p.reachable_total >= p.enforced_total


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
