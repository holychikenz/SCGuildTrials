"""Offline smoke test of the bake-off CLI (finding 17)."""

from __future__ import annotations

import types

import pytest

from src import build, optimize_bakeoff as bakeoff


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(bakeoff, "STRATEGIES", ["random", "proxy_greedy"])
    monkeypatch.setattr(bakeoff, "_HAS_SCIPY", False)


def test_cli_runs_a_tiny_bakeoff_and_labels_the_objective(small, capsys):
    assert bakeoff.main(["--seeds", "1", "--sizes", "12"]) == 0
    out = capsys.readouterr().out
    assert "synthetic roster n=12" in out
    assert "mean_obj" in out and "mean_cr" not in out
    assert "proxy_greedy" in out and "random" in out


def test_csv_is_not_advertised_and_not_accepted(small):
    assert "--csv" not in bakeoff.__doc__
    with pytest.raises(SystemExit):
        bakeoff.main(["--csv"])


def test_live_roster_is_the_builds_member_assembly(small, monkeypatch, capsys):
    """--live must race the members build.py races (roster merge, gear, shrines),
    not the bare member tab."""
    assembled = bakeoff._synthetic_roster(12, seed=7, skills=[])
    seen = {}

    def fetch_guild(site, draw):
        seen["site"], seen["skills"] = site.key, draw.skills
        return types.SimpleNamespace(members=assembled)

    monkeypatch.setattr(build, "_fetch_guild", fetch_guild)
    assert bakeoff.main(["--seeds", "1", "--sizes", "", "--live"]) == 0
    assert seen["site"] == "sc"
    assert "LIVE SC roster n=12" in capsys.readouterr().out
