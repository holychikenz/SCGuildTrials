"""simulate_trial's re-derivation must match the shipped race (finding 14)."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

np = pytest.importorskip("numpy")

from src import config, simulate_trial, trials  # noqa: E402
from src.reader import MemberRow, SkillEntry  # noqa: E402


def _member(name, level, gathering):
    skills = {sk: SkillEntry(level=level, tool=False, top=False, bot=False)
              for sk in config.SKILLS}
    m = MemberRow(name=name, main_classes="", flex="", flex_levels=[], skills=skills)
    return replace(m, gear_bonuses={"Foraging": (0.0, 0.0, 0.0, gathering)})


def test_taus_match_simulate_race_for_a_mixed_doubling_gathering_party(monkeypatch):
    monkeypatch.setattr(config, "GEAR_SOURCE_ENABLED", True)
    # Member 0 has NO gathering gear; the old build_party applied its doubling chance
    # to everyone, ~6.5% off simulate_race on a party like this.
    party_rows = [_member(f"m{i}", 100 + 3 * i, 0.0 if i == 0 else 0.12)
                  for i in range(8)]
    party = simulate_trial.build_party(party_rows, "Foraging")
    assert len(set(party.delta.tolist())) == 2
    taus, _ = simulate_trial.analytic(party)
    ref = trials.simulate_race(party_rows, "Foraging")
    checked = 0
    for s in ref.timeline:
        if s.cumulative_time is not None:
            assert taus[s.tier - 1] == pytest.approx(s.cumulative_time, rel=1e-9)
            checked += 1
    assert checked >= 2


def test_simulate_applies_each_members_own_doubling(monkeypatch):
    monkeypatch.setattr(config, "GEAR_SOURCE_ENABLED", True)
    rows = [_member("a", 120, 0.0), _member("b", 120, 0.5)]
    party = simulate_trial.build_party(rows, "Foraging", max_tier=3)
    sim = simulate_trial.simulate(party, runs=400, dt=5.0, seed=1)
    det, _ = simulate_trial.analytic(party)
    # The dice mean sits on the deterministic time when each member doubles at its
    # own rate (a single shared chance would bias it by the gap between the two).
    assert np.nanmean(sim[:, 2]) == pytest.approx(det[2], rel=0.02)


def test_published_sigma_is_not_a_stale_hard_coded_constant():
    """The default is derived per run (dice sigma in quadrature with
    config.RISK_SIGMA_SYSTEMATIC), not the old campaign's 0.0231."""
    assert 0.0231 not in simulate_trial.main.__code__.co_consts
    assert "RISK_SIGMA_SYSTEMATIC" in simulate_trial.main.__code__.co_names
