"""End-to-end: build.main() over stubbed fetchers, asserting on the written _site.

The network is cut at two levels: every sheet fetch that a test does not care about
is replaced at the fetcher (as in test_build.py's _stub_fetch_guild_for_cap), and a
test that is ABOUT the network replaces ``requests.get`` itself so the real
``reader.fetch_text`` retry/convert path runs. The optimiser is real, on a small
seeded roster and one cheap pipeline.
"""

from __future__ import annotations

import pytest

from src import build, config, draw as draw_model, reader, scraper
from tests.golden_fixture import golden_members

DRAW = ["Milking", "Enhancing", "Cooking", "Brewing"]


class _Resp:
    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise reader.requests.HTTPError(f"{self.status_code} Server Error")


def _signup_csv(tab: str) -> str:
    return "User," + ",".join(DRAW) + "\n"


@pytest.fixture
def site_env(monkeypatch, tmp_path):
    """Stub every fetch main() makes; returns the output dir and a dict of hooks."""
    members = golden_members()[:10]
    out = tmp_path / "_site"
    monkeypatch.setattr(build, "OUTPUT_DIR", out)
    monkeypatch.setattr(config, "BUILD_PARALLEL", False)
    monkeypatch.setattr(config, "OPT_ENSEMBLE_PIPELINES", ["proxy_greedy"])
    monkeypatch.setattr(config, "ROSTER_SOURCE_ENABLED", False)
    monkeypatch.setattr(config, "BUILDINGS_SOURCE_ENABLED", False)
    monkeypatch.setattr(config, "TRIALS_BUFF_LEVEL_SLIDER", False)
    monkeypatch.setattr(reader.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        build.draw_model, "load_draw",
        lambda tab=None: draw_model.TrialDraw(skills=list(DRAW), date=""),
    )
    monkeypatch.setattr(build, "fetch_csv", lambda: "csv")
    monkeypatch.setattr(build, "parse", lambda text: list(members))
    hooks = {"member_status": {}}

    def scrape_member_tab(tab):
        status = hooks["member_status"].get(tab)
        if status is not None:  # drive the REAL fetch path into a failing response
            monkeypatch.setattr(reader.requests, "get", lambda url, timeout: _Resp(status))
            return scraper.scrape_member_tab(tab)
        return scraper.GuildData(
            tab=tab, fetched_at="t", member_count=len(members), members=list(members)
        )

    monkeypatch.setattr(build, "scrape_member_tab", scrape_member_tab)
    monkeypatch.setattr(build.signup_model, "fetch_signup_csv", _signup_csv)
    monkeypatch.setattr(build, "_fetch_combat", lambda site, csv: (None, "stub"))
    monkeypatch.setattr(build, "_fetch_building_value", lambda site: (None, "stub"))
    return out, hooks


def _tab(key: str) -> str:
    return [s for s in build.GUILD_SITES if s.key == key][0].member_tab


def test_full_build_writes_both_guilds(site_env):
    out, _ = site_env
    assert build.main() == 0
    assert (out / "index.html").exists() and (out / "trials.html").exists()
    assert (out / "li" / "index.html").exists()


def test_li_fetch_503_still_ships_sc(site_env, capsys):
    out, hooks = site_env
    hooks["member_status"][_tab("li")] = 503
    assert build.main() == 0
    assert (out / "index.html").exists() and (out / "data.json").exists()
    assert not (out / "li" / "index.html").exists()
    err = capsys.readouterr().err
    assert "li skipped" in err and "503" in err


def test_sc_fetch_503_fails_the_build(site_env):
    _, hooks = site_env
    hooks["member_status"][_tab("sc")] = 503
    assert build.main() == 1


def test_li_optimiser_crash_still_ships_sc(site_env, monkeypatch, capsys):
    out, _ = site_env
    real = build._compute_unit

    def unit(job):
        if job["site_key"] == "li":
            raise ValueError("optimiser exploded")
        return real(job)

    monkeypatch.setattr(build, "_compute_unit", unit)
    assert build.main() == 0
    assert (out / "index.html").exists()
    assert not (out / "li" / "index.html").exists()
    assert "li skipped (ValueError: optimiser exploded)" in capsys.readouterr().err


def test_sc_optimiser_crash_still_fails(site_env, monkeypatch):
    def unit(job):
        raise ValueError("optimiser exploded")

    monkeypatch.setattr(build, "_compute_unit", unit)
    with pytest.raises(ValueError):
        build.main()


def test_li_render_crash_still_ships_sc(site_env, monkeypatch, capsys):
    out, _ = site_env
    real = build._write_guild

    def write(site, *a, **k):
        if site.key == "li":
            raise KeyError("render")
        return real(site, *a, **k)

    monkeypatch.setattr(build, "_write_guild", write)
    assert build.main() == 0
    assert (out / "index.html").exists()
    assert "li skipped" in capsys.readouterr().err


def test_rendered_pages_carry_the_right_text(site_env):
    """Finding 6: no double-escaped separator, no stale cap claim, and each guild's
    sign-up page names its OWN sign-up tab."""
    out, _ = site_env
    assert build.main() == 0
    for d in (out, out / "li"):
        trials = (d / "trials.html").read_text()
        assert "&amp;middot;" not in trials
        assert "optimised assignment via" in trials and " · " in trials
        assert "largest party ever observed" not in trials
        assert "Marginal seat:" in trials
    li_signup = (out / "li" / "signup.html").read_text()
    assert "LI Trial Signup" in li_signup and "SC Trial Signup" not in li_signup
    assert "SC Trial Signup" in (out / "signup.html").read_text()


def test_inactive_signup_page_names_the_guilds_own_tab():
    li = [s for s in build.GUILD_SITES if s.key == "li"][0]
    page = build._render_signup_inactive_html("reason", "now", li)
    assert "LI Trial Signup" in page and "SC Trial Signup" not in page


def test_li_non_runtime_fetch_error_still_ships_sc(site_env, monkeypatch, capsys):
    out, _ = site_env
    real = build.scrape_member_tab

    def scrape(tab):
        if tab == _tab("li"):
            raise ValueError("odd cell")
        return real(tab)

    monkeypatch.setattr(build, "scrape_member_tab", scrape)
    assert build.main() == 0
    assert (out / "index.html").exists() and not (out / "li" / "index.html").exists()
    assert "li skipped (ValueError: odd cell)" in capsys.readouterr().err


def test_li_unit_jobs_error_still_ships_sc(site_env, monkeypatch, capsys):
    out, _ = site_env
    real = build._unit_jobs

    def unit_jobs(site, inputs, draw):
        if site.key == "li":
            raise KeyError("cap")
        return real(site, inputs, draw)

    monkeypatch.setattr(build, "_unit_jobs", unit_jobs)
    assert build.main() == 0
    assert (out / "index.html").exists()
    assert "li skipped (KeyError" in capsys.readouterr().err


def test_profile_tool_name_never_reaches_the_site(site_env, monkeypatch):
    """A tool from an uploaded profile prices the race but is never published."""
    from dataclasses import replace

    from src import profiles, roster

    out, _ = site_env
    members = [replace(m, character_id=str(9000 + i))
               for i, m in enumerate(golden_members()[:10])]
    monkeypatch.setattr(build, "parse", lambda text: list(members))
    monkeypatch.setattr(build, "scrape_member_tab", lambda tab: scraper.GuildData(
        tab=tab, fetched_at="t", member_count=len(members), members=list(members)))
    monkeypatch.setattr(config, "ROSTER_SOURCE_ENABLED", True)
    monkeypatch.setattr(config, "ROSTER_MIN_JOIN_RATE", 0.0)
    monkeypatch.setattr(roster, "scrape_roster_tab", lambda tab: [])
    items = ";".join(f"{h.rsplit('/', 1)[-1]}:17" for h, name in
                     profiles.TOOL_BY_HRID.items() if name.startswith("Celestial"))
    row = [None] * profiles.REQUIRED_COLUMNS
    row[profiles._COL["items"]] = items
    profs = {}
    for m in members:
        row[profiles._COL["characterId"]] = m.character_id
        profs[int(m.character_id)] = profiles.parse_row(row)
    monkeypatch.setattr(build.profiles_model, "load", lambda tab: (profs, "synthetic"))

    assert build.main() == 0
    trials = (out / "trials.json").read_text()
    assert '"tool_source":"profiles"' in trials
    for f in out.rglob("*"):
        if f.is_file() and f.suffix in {".json", ".html", ".js"}:
            text = f.read_text(errors="replace")
            assert "Celestial" not in text and "celestial_" not in text, f
