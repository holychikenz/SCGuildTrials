"""Phase G6: reconcile each per-item gear slice against its predicted band.

Not imported by the build. Run:
    .venv/bin/python research/scratch/gear_reconcile.py

WHAT IT MEASURES, AND WHY IT HOLDS THE ASSIGNMENT FIXED. The bands predicted in
research/per-item-gear.md §7 are claims about RATE TERMS, not about which parties
the search picks. So each slice is priced by RE-SCORING the baseline lineup —
`trials.score_assignment` on the assignment `choose_assignment` found with the
gear off — which isolates the repricing from the search's own response to it. A
slice outside its band is then unambiguously a bug in the slice.

The final row does run a fresh search with every slice on, because that is what
the flip actually publishes and the search's response to a better rate model is
exactly the thing worth seeing before committing to it.

Fixed seed (config.TRIAL_OPTIMIZER_SEED) and this week's live draw throughout, so
every row differs from the baseline in the gear switches and nothing else.
"""
from __future__ import annotations

import time

from src import build, config, draw as draw_model, gear, roster, trials
from src.scraper import scrape_member_tab

SLICES = [
    ("cape", ["GEAR_USE_CAPE"]),
    ("family piece", ["GEAR_USE_FAMILY_PIECE"]),
    ("garments", ["GEAR_USE_GARMENTS"]),
    ("accessories", ["GEAR_USE_ACCESSORIES"]),
    ("ALL SLICES", ["GEAR_USE_CAPE", "GEAR_USE_FAMILY_PIECE",
                    "GEAR_USE_GARMENTS", "GEAR_USE_ACCESSORIES"]),
]
ALL_SWITCHES = ["GEAR_USE_CAPE", "GEAR_USE_FAMILY_PIECE",
                "GEAR_USE_GARMENTS", "GEAR_USE_ACCESSORIES"]


def load(guild: str):
    rows = roster.scrape_roster_tab(config.ROSTER_TABS[guild])
    members = scrape_member_tab(config.TABS[guild]).members
    merged, _ = roster.merge(members, roster.join(members, rows), guild)
    trials.audit_roster_tools(merged)
    return merged, rows


def set_slices(on: list[str]) -> None:
    for switch in ALL_SWITCHES:
        setattr(config, switch, switch in on)


def summarise(result) -> dict:
    d = result.to_dict()
    return {
        "points": d.get("total_points"),
        "credit": d.get("total_credit_points"),
        "expected": d.get("total_expected_points"),
        "trials": [
            (t["skill"], t["tier_reached"], t.get("time_slack_fraction"),
             t.get("clear_probability"), t.get("expected_points"))
            for t in d["trials"]
        ],
    }


def row(label: str, base: dict, got: dict) -> None:
    thin_base = min(t[3] for t in base["trials"])
    thin_got = min(t[3] for t in got["trials"])
    print(f"  {label:14s} points {got['points']:>7} ({got['points'] - base['points']:+})"
          f"   credit {got['credit']:9.2f} ({got['credit'] - base['credit']:+8.2f})"
          f"   E {got['expected']:9.2f} ({got['expected'] - base['expected']:+8.2f})"
          f"   thinnest P {thin_got:.4f} ({thin_got - thin_base:+.4f})")


def main() -> None:
    week = draw_model.load_draw(config.DRAW_SOURCE_TAB)
    print(f"draw: {', '.join(week.skills)}   seed {config.TRIAL_OPTIMIZER_SEED}\n")

    for guild in config.ROSTER_TABS:
        members, rows = load(guild)
        cap = config.party_cap(guild)
        stats_all = None

        # --- baseline: the shipped build, gear off --------------------------
        config.GEAR_SOURCE_ENABLED = False
        set_slices(ALL_SWITCHES)
        t0 = time.time()
        assignment = trials.choose_assignment(
            members, list(week.skills), seed=config.TRIAL_OPTIMIZER_SEED, cap=cap
        )
        base = summarise(trials.score_assignment(
            assignment, members, list(week.skills),
            seed=config.TRIAL_OPTIMIZER_SEED, cap=cap,
        ))
        print(f"=== {guild.upper()}   baseline search {time.time() - t0:.0f}s")
        print(f"  {'baseline':14s} points {base['points']:>7}      "
              f"   credit {base['credit']:9.2f}            "
              f"   E {base['expected']:9.2f}            "
              f"   thinnest P {min(t[3] for t in base['trials']):.4f}")

        # --- each slice, on the SAME lineup ---------------------------------
        config.GEAR_SOURCE_ENABLED = True
        for label, switches in SLICES:
            set_slices(switches)
            stats = gear.measure([r.gear for r in rows], guild)
            for m in members:
                m.gear_bonuses = gear.resolve(m, stats)
            if label == "ALL SLICES":
                stats_all = stats
            row(label, base, summarise(trials.score_assignment(
                assignment, members, list(week.skills),
                seed=config.TRIAL_OPTIMIZER_SEED, cap=cap,
            )))

        # --- and one fresh search with everything on ------------------------
        set_slices(ALL_SWITCHES)
        for m in members:
            m.gear_bonuses = gear.resolve(m, stats_all)
        t0 = time.time()
        fresh = trials.choose_assignment(
            members, list(week.skills), seed=config.TRIAL_OPTIMIZER_SEED, cap=cap
        )
        got = summarise(trials.score_assignment(
            fresh, members, list(week.skills),
            seed=config.TRIAL_OPTIMIZER_SEED, cap=cap,
        ))
        print(f"  --- fresh search with every slice on ({time.time() - t0:.0f}s)")
        row("RE-OPTIMISED", base, got)
        print("  per trial (baseline -> re-optimised):")
        for b, g in zip(base["trials"], got["trials"]):
            print(f"    {b[0]:14s} tier {b[1]}->{g[1]}   margin "
                  f"{b[2]:.4f}->{g[2]:.4f}   P {b[3]:.4f}->{g[3]:.4f}   "
                  f"E {b[4]:.2f}->{g[4]:.2f}")
        print()
        config.GEAR_SOURCE_ENABLED = False


if __name__ == "__main__":
    main()
