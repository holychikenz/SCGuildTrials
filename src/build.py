"""Entry point: fetch -> parse -> process -> write static site into _site/.

Run with:  python -m src.build

Exits non-zero on any fetch/parse/structure error so CI fails loudly.
"""

from __future__ import annotations

import html
import json
import os
import sys
from concurrent import futures
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import config
from . import draw as draw_model
from . import roster as roster_model
from . import signup as signup_model
from . import trials as trials_model
from .processor import process
from .reader import MemberRow, SheetStructureError, fetch_csv, parse
from .scraper import scrape_member_tab

OUTPUT_DIR = Path("_site")

# The trials page ships ONCE per guild, at the published community-buff level
# (``config.COMMUNITY_BUFF_LEVEL``), and carries the whole 1..20 ladder inline behind
# a selector: one optimiser run, re-rated at each rung by ``trials.run_week_ladder``.
#
# It used to ship TWICE, the second copy a maxed-buff counterfactual at
# ``config.COMMUNITY_BUFF_MAX_LEVEL``, and the argument for two files rather than one
# was that each was a WHOLE separate optimiser run — different parties, not merely
# different rates — so no client-side switch could stand in for it, and that two full
# copies of the roster markup in one document would collide on every DOM id the
# player search jumps to.
#
# Both halves of that argument dissolve once the parties are held FIXED. There is one
# roster, so there are no duplicate ids; and the swap is arithmetic already done at
# build time, so the browser recomputes nothing. What the selector cannot do is
# redraw the parties, which is why every rung is labelled a lower bound — see
# ``config.TRIALS_BUFF_LEVEL_SLIDER``. The counterfactual's whole path is still here
# and still tested, one config line from returning.
TRIALS_PAGE = "trials.html"
TRIALS_JSON = "trials.json"
TRIALS_MAXBUFF_PAGE = "trials-maxbuffs.html"
TRIALS_MAXBUFF_JSON = "trials-maxbuffs.json"

# UNLISTED PAGES. Readers who met BOTH the full optimum (``trials.html``) and the
# sign-up plan (``signup.html``) took them for rival answers to one question, when
# they answer two: the ceiling over the whole roster, and the plan over the members
# who actually volunteered. They necessarily disagree, which is the confusion. The
# full optimum is the answer we publish, so ``signup.html`` is now UNLISTED — still
# built, still written, still served at its own URL with its JSON, but nothing links
# TO it any more (as was already true of ``trials-maxbuffs.html``). Reaching it means
# knowing the URL.
#
# Note the asymmetry: signup.html keeps its own OUTBOUND links to trials.html, in the
# nav and in the prose of its comparison card. Those cannot make it discoverable, and
# they point a reader who arrived by URL back at the page we do publish.
#
# To relist it, restore the <a href="signup.html"> in the ``.nav`` paragraph of
# ``_render_html`` (index) and ``_render_trials_html``.


# ---------------------------------------------------------------------------
# Per-guild site definitions
# ---------------------------------------------------------------------------
# The guild sheet hosts more than one sub-guild (Survey Corps, Lactose
# lntolerance), each with its OWN member tab (``config.TABS``) and sign-up tab
# (``signup.SIGNUP_TABS``). ``main`` builds the WHOLE pipeline once per guild:
# Survey Corps into the site root (``_site/``, unchanged URLs) and every other
# guild into its own sub-directory (``_site/li/``). Pages inside a guild's
# directory link to each other with plain relative hrefs (``trials.html`` etc.),
# which resolve within that directory; the only cross-directory link is the
# sibling-guild jump in the nav (``sibling_home``). The trial *draw* is shared — read
# ONCE from the game-written tab named by ``config.DRAW_SOURCE_TAB``
# (``draw.load_draw``) and handed to every guild. Each guild's OWN sign-up tab is
# still read for its ticks, and cross-checked against that draw: the game refreshes
# the two guilds' tabs at different moments, so a guild whose tab still lists a
# previous cycle has its plan withheld rather than built from last week's volunteers.
@dataclass(frozen=True)
class GuildSite:
    """One guild's build: which tabs to read, where to write, how to label it."""

    key: str            # config.TABS / signup.SIGNUP_TABS key: "sc" | "li"
    title: str          # page <title> / <h1>, e.g. "SURVEY CORPS"
    subdir: str         # output dir under _site ("" = root, "li" = _site/li)
    # index.html source: True -> the gid=0 published register (reader.fetch_csv/
    # parse), which exists only for Survey Corps; False -> the guild's gviz
    # member tab (config.TABS[key]), used for every other guild.
    use_register_csv: bool
    required: bool      # True -> a build failure is fatal (non-zero exit, blocks
                        # deploy); False -> failure is a warning, other guilds
                        # still ship (the whole _site deploys atomically).
    sibling_title: str  # the OTHER guild's title, for the cross-guild nav link
    sibling_home: str   # relative href from THIS guild's pages to the other's index

    @property
    def member_tab(self) -> str:
        return config.TABS[self.key]

    @property
    def roster_tab(self) -> str:
        """This guild's scripted per-character harvest tab (src/roster.py).

        A SECOND tab, written by a separate Apps Script deployment, carrying
        levels, houses, tools + their enhancement and per-member shrine levels.
        Read only when config.ROSTER_SOURCE_ENABLED is on.
        """
        return config.ROSTER_TABS[self.key]

    @property
    def signup_tab(self) -> str:
        return signup_model.SIGNUP_TABS[self.key]

    @property
    def party_cap(self) -> int:
        """This guild's seats-per-party cap (config.TRIAL_PARTY_CAPS).

        Per guild since 2026-08-21: SC runs 28, LI 26. Passed explicitly into
        every optimiser call for this guild, so no page is ever planned against
        the guild-less default in config.TRIAL_PARTY_CAP.
        """
        return config.party_cap(self.key)

    @property
    def out_dir(self) -> Path:
        return OUTPUT_DIR / self.subdir if self.subdir else OUTPUT_DIR


GUILD_SITES = [
    GuildSite(
        key="sc", title="SURVEY CORPS", subdir="",
        use_register_csv=True, required=True,
        sibling_title="LACTOSE INTOLERANCE", sibling_home="li/index.html",
    ),
    GuildSite(
        key="li", title="LACTOSE INTOLERANCE", subdir="li",
        use_register_csv=False, required=False,
        sibling_title="SURVEY CORPS", sibling_home="../index.html",
    ),
]


def _badge(present: bool, label: str) -> str:
    """Render a small T/T/B style badge; filled when present, muted when not."""
    cls = "badge on" if present else "badge off"
    return f'<span class="{cls}" title="{html.escape(label)}">{label[0]}</span>'


def _render_html(data: dict, site: "GuildSite") -> str:
    skills = data["skills"]

    # Summary table header cells.
    summary_rows = "".join(
        "<tr>"
        f"<td>{html.escape(s['skill'])}</td>"
        f"<td class=num>{'' if s['average_level'] is None else s['average_level']}</td>"
        f"<td class=num>{s['levels_reported']}</td>"
        f"<td class=num>{s['tool_count']}</td>"
        f"<td class=num>{s['top_count']}</td>"
        f"<td class=num>{s['bot_count']}</td>"
        "</tr>"
        for s in data["skill_summary"]
    )

    # Members table header: Member | Main | Flex | <skill> x N.
    skill_headers = "".join(f"<th>{html.escape(s)}</th>" for s in skills)

    member_rows = []
    for m in data["members"]:
        cells = [
            f"<th scope=row>{html.escape(m['name'])}</th>",
            f"<td>{html.escape(m['main_classes'])}</td>",
            f"<td>{html.escape(m['flex'])}</td>",
        ]
        for skill in skills:
            entry = m["skills"][skill]
            level = "" if entry["level"] is None else entry["level"]
            badges = (
                _badge(entry["tool"], "Tool")
                + _badge(entry["top"], "Top")
                + _badge(entry["bot"], "Bot")
            )
            cells.append(
                f'<td class=skillcell><span class=lvl>{level}</span>'
                f'<span class=badges>{badges}</span></td>'
            )
        member_rows.append("<tr>" + "".join(cells) + "</tr>")

    members_html = "".join(member_rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(site.title)} - Skill Register</title>
<style>
  :root {{
    --bg: #0f1115; --panel: #171a21; --line: #2a2f3a;
    --text: #e6e8ec; --muted: #99a0ad; --accent: #6ea8fe;
    --on: #3ecf8e; --off: #3a3f4b;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 2rem 1.25rem 4rem;
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text);
  }}
  header {{ max-width: 1100px; margin: 0 auto 1.5rem; }}
  h1 {{ margin: 0 0 .25rem; font-size: 1.6rem; letter-spacing: .5px; }}
  h2 {{ font-size: 1.05rem; margin: 2rem 0 .6rem; color: var(--accent); }}
  .meta {{ color: var(--muted); font-size: .85rem; }}
  main {{ max-width: 1100px; margin: 0 auto; }}
  .scroll {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }}
  table {{ border-collapse: collapse; width: 100%; background: var(--panel); }}
  th, td {{ padding: .45rem .6rem; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }}
  thead th {{ position: sticky; top: 0; background: #1d222c; font-size: .8rem; text-transform: uppercase; letter-spacing: .4px; color: var(--muted); }}
  tbody th {{ font-weight: 600; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .skillcell {{ text-align: center; }}
  .lvl {{ display: inline-block; min-width: 2ch; font-variant-numeric: tabular-nums; margin-right: .35rem; }}
  .badges {{ display: inline-flex; gap: 2px; vertical-align: middle; }}
  .badge {{
    display: inline-grid; place-items: center; width: 16px; height: 16px;
    border-radius: 3px; font-size: 10px; font-weight: 700;
  }}
  .badge.on {{ background: var(--on); color: #06231a; }}
  .badge.off {{ background: var(--off); color: #6b7180; }}
  tbody tr:hover {{ background: #1b2029; }}
  .nav {{ margin: .5rem 0 0; font-size: .95rem; }}
  .nav a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
  .nav a:hover {{ text-decoration: underline; }}
  footer {{ max-width: 1100px; margin: 2rem auto 0; color: var(--muted); font-size: .8rem; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(site.title)} &mdash; Skill Register</h1>
  <p class="meta">Milky Way Idle guild &middot; {data['member_count']} members &middot;
     generated {html.escape(data['generated_at'])} (UTC)</p>
  <p class="nav"><a href="trials.html">Guild Trials &rarr;</a>
     &nbsp;&middot;&nbsp; <a href="{site.sibling_home}">{html.escape(site.sibling_title)} &rarr;</a></p>
</header>
<main>
  <h2>Per-skill summary</h2>
  <div class="scroll">
    <table>
      <thead>
        <tr><th>Skill</th><th class=num>Avg level</th><th class=num>Reported</th>
            <th class=num>Tools</th><th class=num>Tops</th><th class=num>Bots</th></tr>
      </thead>
      <tbody>{summary_rows}</tbody>
    </table>
  </div>

  <h2>Members</h2>
  <p class="meta">Each skill cell shows level and Tool / Top / Bot ownership
     (filled = owned).</p>
  <div class="scroll">
    <table>
      <thead>
        <tr><th>Member</th><th>Main</th><th>Flex</th>{skill_headers}</tr>
      </thead>
      <tbody>{members_html}</tbody>
    </table>
  </div>
</main>
<footer>
  Static build from the public guild sheet. No credentials, read-only.
</footer>
</body>
</html>
"""


def _num(value, digits: int = 2) -> str:
    """Format a float for display; '' for None."""
    if value is None:
        return ""
    return f"{value:,.{digits}f}"


def _margin_view(trial: dict) -> dict:
    """Adapt a ``trials.json`` trial into the shape ``_margin_phrase`` expects.

    The sign-up plan stores ``clear_seconds`` outright; the full-optimum result
    stores only its ``timeline``, so the clock reading is read back off the last
    CLEARED step. Derived rather than duplicated, so the two pages can never
    disagree about when a tier was banked.
    """
    secs = next(
        (
            s["cumulative_time"]
            for s in reversed(trial.get("timeline") or [])
            if s.get("cleared") and s.get("cumulative_time") is not None
        ),
        None,
    )
    return {
        "tier_reached": trial.get("tier_reached") or 0,
        "clear_seconds": secs,
        "slack_fraction": (
            None if secs is None
            else 1.0 - secs / config.TRIAL_TIME_BUDGET_SECONDS
        ),
    }


def _sorted_roster(trial: dict) -> list[dict]:
    """Roster pre-sorted by rate at the final tier, descending (default sort).

    This is the server-side render order for the roster table; the client-side
    sorter's initial arrow state reflects the same default (see the page JS).
    """
    return sorted(trial["roster"], key=lambda r: r["rate_final"], reverse=True)


def _credit_points(entry: dict) -> float:
    """``credit_points``, falling back to the step award when the key is absent.

    Defensive by policy (the degrade-don't-fail rule ``draw.py`` already follows): a
    ``trials.json`` / ``signup.json`` written before the 2026-08-11 patch carries no
    credit figure at all, and the page must still render the honest equivalent — with
    no partial credit the two are equal by construction — rather than raise or print a
    dash where a score belongs.
    """
    credit = entry.get("credit_points")
    return float(entry.get("points") or 0) if credit is None else float(credit)


def _tier_phrase(trial: dict) -> str:
    """``tier 11 + 22.8% into tier 12`` &mdash; the banked tier, then the part-finished one.

    Points are no longer a pure step function of the banked tier: the patch pays
    ``config.TRIAL_PARTIAL_CREDIT_RATE`` of a tier for progress into the next one, so
    how far the party got is part of the score and belongs beside the tier, not buried.
    """
    tier = trial.get("tier_reached") or 0
    fraction = trial.get("partial_fraction") or 0.0
    if fraction <= 0.0:
        return f"tier <strong>{tier}</strong>"
    return f"tier <strong>{tier}</strong> + {_pct(fraction)} into tier {tier + 1}"


def _points_phrase(trial: dict) -> str:
    """``1,211.4 points (1,200 banked)`` &mdash; credit score, then the confirmed award.

    Both, because they answer different questions. ``credit_points`` is what the
    optimizer maximised and what the patch says the trial is worth; ``points`` is the
    step award for the tiers actually banked, which is the only figure the game's own
    schedule has ever been confirmed against.
    """
    return (
        f"{_cp(_credit_points(trial))} points "
        f"({_gp(trial.get('points') or 0)} banked)"
    )


def _expected_phrase(trial: dict) -> str:
    """`` &middot; 1,275.7 expected`` &mdash; empty when the expectation is absent.

    The deterministic score prices a tier held at even odds as a certainty, so it is
    optimistic exactly where the margin is thin. This is the same score integrated over
    the calibrated shock. Shown only when it differs from the deterministic figure by
    enough to matter: on a comfortable trial the two agree to within a rounding error,
    and printing both would be noise.
    """
    expected = trial.get("expected_points")
    if expected is None:
        return ""
    deterministic = _credit_points(trial)
    if deterministic is None or abs(deterministic - expected) < 0.5:
        return ""
    return (
        f' &middot; <strong>{_cp(expected)} expected</strong> '
        f'<span class="muted-text">({_cp(expected - deterministic)} on the bet)</span>'
    )


def _marginal_seat_phrase(trial: dict, cap: int) -> str:
    """The weakest seated member's share of party rate, against the break-even.

    WHY THIS IS ON THE PAGE. Partial credit prices a marginal seat: a member earns
    their place iff they add more than roughly ``1/(100 + N)`` of the party's
    throughput, because an extra head raises EVERY tier's target by 1% (the
    ``(1 + Players/100)`` headcount term in TotalWork). Under the old step objective
    that number was invisible — every candidate from level 140 down to level 10 scored a
    delta of exactly zero — so being wrong about the party cap cost nothing
    measurable. It now costs points in WHICHEVER DIRECTION it is wrong, and the cap
    is unconfirmed: 20 is the largest skilling party ever observed
    (``research/trial-tabs.md``), while config.TRIAL_PARTY_CAPS ships 28 (SC) and
    26 (LI). ``cap`` is THIS guild's, taken from the week it rendered
    (``week["cap"]``) rather than re-read from config, so the line quotes the number
    the plan on the page was actually built with. If the real cap is 20 then every
    tier, margin and probability on this page is optimistic by four phantom
    contributors; if there is no cap at 24 the guild is leaving points on the table and
    this tool is quietly telling it to. The line publishes that exposure rather than
    hiding it.

    Two decimals, unlike :func:`_pct`: both figures sit near 1%, and a single decimal
    cannot separate the two sides of the very break-even the line exists to compare.
    """
    rates = [r.get("rate_final") or 0.0 for r in (trial.get("roster") or [])]
    total = sum(rates)
    if not rates or total <= 0.0:
        return ""
    share = min(rates) / total
    size = trial.get("party_size") or len(rates)
    breakeven = 1.0 / (100.0 + size)
    pays = share >= breakeven
    return (
        f'Marginal seat: weakest seated contributes '
        f'<span class="{"ok-text" if pays else "warn-text"}">'
        f'{share * 100:.2f}%</span> of party rate, against a '
        f'{breakeven * 100:.2f}% break-even at {size} seats &mdash; '
        + (
            "so every seat pays for itself."
            if pays
            else "so the weakest seat costs more than it adds."
        )
        + f' The cap ({cap}) is itself unconfirmed &mdash; 20 is the '
          f'largest party ever observed &mdash; and partial credit is what made being '
          f'wrong about it cost measurable points.'
    )


def _fav_button(name: str) -> str:
    """The pin control (a hollow star) for one member.

    Rendered hollow and unpressed for EVERY member; the page script fills in the
    ones this reader has pinned once it has read localStorage. Server-side state
    is impossible here — the pins are per-device and the page is a static file
    cached by GitHub Pages — so the honest starting state is "none pinned", and a
    reader with pins sees them fill in on load rather than seeing the wrong ones
    baked in.
    """
    safe = html.escape(name)
    return (
        f'<button type="button" class="fav" data-fav="{safe}" aria-pressed="false"'
        f' title="Pin {safe} to the top of this page"'
        f' aria-label="Pin {safe} to the top of this page">&#9734;</button>'
    )


def _member_cell(name: str) -> str:
    """A roster row's member cell: the pin control, then the name.

    ``data-sort`` carries the BARE name because the client-side text sorter falls
    back to ``textContent`` when the attribute is absent — and textContent here
    begins with the star glyph, which would sort every row identically.
    """
    safe = html.escape(name)
    return f'<th scope=row data-sort="{safe}">{_fav_button(name)}{safe}</th>'


def _assign_summary(trial: dict) -> tuple[str, str, str]:
    """(what the trial scored, how narrowly, band class) as PLAIN text.

    Denormalised onto every member's search-index entry so the pinned panel can
    describe someone's trial from the index alone, with no second lookup table.
    Plain text rather than HTML because the panel writes it through
    ``textContent`` — an ``&middot;`` would render literally.
    """
    view = _margin_view(trial)
    secs = view["clear_seconds"]
    scored = f"Tier {trial['tier_reached']} · {_cp(_credit_points(trial))} credit pts"
    if (trial.get("tier_reached") or 0) < 1 or secs is None:
        return scored, "no tier banked", "danger-text"
    margin = (
        f"banked at {_num(secs, 0)}s of "
        f"{_num(config.TRIAL_TIME_BUDGET_SECONDS, 0)}s · "
        f"{_pct(view['slack_fraction'])} spare"
    )
    return scored, margin, _slack_band(view["slack_fraction"])


# ---------------------------------------------------------------------------
# The level-dependent fragments of a trial card
# ---------------------------------------------------------------------------
# Everything below is a pure function of ONE trial dict, and every one of them is
# called twice: once to render the page at the published community-buff level, and
# once per rung to fill the selector's inline ladder (_buff_ladder_payload). Keeping
# them as named fragments rather than inlining them in _render_trial_card is what
# lets the browser swap a level without a second copy of the model, or of the
# formatting rules, or of the band thresholds living in JavaScript.


def _card_headline(trial: dict) -> str:
    """Party size, tier, points, expectation — the card's first meta line."""
    return (
        f"Party size {trial['party_size']} &middot;\n       "
        f"{_tier_phrase(trial)} &middot; {_points_phrase(trial)}"
        f"{_expected_phrase(trial)}"
    )


def _card_safety(trial: dict) -> str:
    """When the last tier was banked and how often it holds — the second meta line."""
    return (
        "Safety:\n       "
        f"{_margin_phrase(_margin_view(trial), config.TRIAL_TIME_BUDGET_SECONDS)}\n       "
        f"{_risk_phrase(trial)}"
    )


def _timeline_cells(trial: dict) -> list[list]:
    """The tier timeline as rows of ALREADY-FORMATTED cells, newest rung last.

    Arrays rather than ``<tr>`` markup because the selector ships one of these per
    rung per trial and the markup is eight times the bytes; arrays of *formatted
    strings* rather than of numbers because the formatting is where the rules are
    (the infinity, the em dash, the progress figure that appears on exactly one
    row), and those rules belong here beside :func:`_num` and not in the page
    script.
    """
    return [
        [
            step["tier"],
            step["tier_level"],
            _num(step["effective_target"], 0),
            _num(step["party_rate"]),
            _num(step["time_to_clear"], 1)
            if step["time_to_clear"] is not None
            else "&infin;",
            _num(step["cumulative_time"], 1)
            if step["cumulative_time"] is not None
            else "&mdash;",
            # Set on the FIRST UNCLEARED step only: a cleared tier is 100% done by
            # definition, and a party that could not move at all made no progress to
            # report. So exactly one row in this table carries a figure, and it is the
            # row the partial credit is paid on. ``.get`` because a pre-patch
            # trials.json has no such key.
            _pct(step.get("progress_fraction")),
            "cleared" if step["cleared"] else "ran out",
        ]
        for step in trial["timeline"]
    ]


def _timeline_rows(trial: dict) -> str:
    """:func:`_timeline_cells`, wrapped in table markup. The server-side render."""
    return "".join(
        '<tr class="{cls}">{cells}</tr>'.format(
            cls="cleared" if row[7] == "cleared" else "failed",
            cells="".join(
                f"<td class=num>{value}</td>" for value in row[:7]
            )
            + f"<td>{row[7]}</td>",
        )
        for row in _timeline_cells(trial)
    )


def _rate_header(trial: dict) -> str:
    """``Rate @T11`` — the roster's last column, which names the tier it is rated at.

    Level-dependent for the same reason the rates under it are: raise the buffs far
    enough and the party finishes a tier it did not reach before.
    """
    final_tier = trial["tier_reached"] if trial["tier_reached"] >= 1 else 1
    return f"Rate @T{final_tier}"


def _stat_strip(week: dict) -> str:
    """The whole summary strip: one tile per trial, then the week's total."""
    # Tile subtitle carries BOTH currencies: the credit score the plan was chosen on,
    # and the step award for the tier actually banked. The tier headline stays the
    # banked one — a part-finished tier is worth points, not a tier.
    tiles = "".join(
        "<div class=\"stat\">"
        f"<div class=stat-skill>{html.escape(t['skill'])}</div>"
        f"<div class=stat-tier>Tier {t['tier_reached']}"
        + (
            f'<span class="stat-pts"> +{_pct(t.get("partial_fraction"))}</span>'
            if (t.get("partial_fraction") or 0.0) > 0.0
            else ""
        )
        + "</div>"
        f"<div class=stat-pts>{_cp(_credit_points(t))} pts "
        f"&middot; {_gp(t['points'])} banked</div>"
        "</div>"
        for t in week["trials"]
    )
    expected_note = _expected_total_note(
        week.get("total_credit_points"), week.get("total_expected_points")
    )
    return (
        tiles
        + '<div class="total">'
        + "<div class=stat-skill>Total</div>"
        + f"<div class=stat-tier>"
          f"{_cp(week.get('total_credit_points') or week['total_points'])}</div>"
        + f"<div class=stat-pts>credit points &middot; "
          f"{_gp(week['total_points'])} from banked tiers{expected_note}</div>"
        + "</div>"
    )


def _render_trial_card(trial: dict, t_index: int, cap: int) -> tuple[str, list[dict]]:
    """Render one trial's section and return (html, assignment_entries).

    ``assignment_entries`` maps each rostered member to this trial and to the
    DOM id of their (pre-sorted) roster row, feeding the page's player search and
    its pinned-members panel. Keys are terse because the whole index ships inline
    in every page: ``n``ame, ``t``rial, ``r``ow id, ``l``evel, ``d``etail (what the
    trial scored), ``m``argin, ``b``and (the margin's colour class).
    """
    skill = html.escape(trial["skill"])
    roster = _sorted_roster(trial)
    scored, margin, band = _assign_summary(trial)
    assign_entries = [
        {
            "n": r["name"], "t": trial["skill"], "r": f"r-{t_index}-{i}",
            "l": r["level"], "d": scored, "m": margin, "b": band,
        }
        for i, r in enumerate(roster)
    ]

    roster_rows = "".join(
        f'<tr id="r-{t_index}-{i}">'
        f"{_member_cell(r['name'])}"
        f"<td class=num data-sort=\"{'' if r['level'] is None else r['level']}\">"
        f"{'' if r['level'] is None else r['level']}</td>"
        f"<td class=cbadges data-sort=\"{int(r['tool']) + int(r['top']) + int(r['bot'])}\">"
        f"{_badge(r['tool'], 'Tool')}{_badge(r['top'], 'Top')}{_badge(r['bot'], 'Bot')}"
        f"</td>"
        f"<td class=num data-sort=\"{r['rate_tier1']!r}\">{_num(r['rate_tier1'])}</td>"
        f"<td class=num data-sort=\"{r['rate_final']!r}\">{_num(r['rate_final'])}</td>"
        "</tr>"
        for i, r in enumerate(roster)
    )

    # Omit the paragraph entirely rather than emit an empty one: the phrase is empty
    # only when the roster carries no usable rates at all (an empty party, or a
    # trials.json old enough to lack rate_final) — a property of the party, not of
    # the buff regime, so a card without this line has none at any level and needs
    # no slot for the selector to fill.
    marginal = _marginal_seat_phrase(trial, cap)
    marginal_html = (
        f'<p class="meta" id="c{t_index}-marg">{marginal}</p>' if marginal else ""
    )

    # The ids on the four meta lines, the rate header and the two table bodies are
    # the selector's swap slots (see _BUFF_JS). They are the ONLY thing the level
    # control touches; the roster's membership, the pins and the search index all
    # stay exactly where they are, because raising a buff does not move anybody.

    # Margin and odds, on the optimum too. The safety pass maximises the margin
    # here, so these cards are the standard the sign-up page reads against — and
    # without them the reader has no way to tell a comfortable optimum from one
    # that is merely lucky.
    card_html = f"""
  <section class="card">
    <h2>{skill}</h2>
    <p class="meta" id="c{t_index}-head">{_card_headline(trial)}</p>
    <p class="meta" id="c{t_index}-safe">{_card_safety(trial)}</p>
    {marginal_html}

    <h3>Roster</h3>
    <p class="meta">Sorted by rate at the final tier (click any header to
       re-sort; click again to reverse).</p>
    <div class="scroll">
      <table class="sortable" data-default-sort="4">
        <thead>
          <tr>
            <th class="sort" data-type="text">Member <span class="arrow">&#8597;</span></th>
            <th class="sort num" data-type="num">Level <span class="arrow">&#8597;</span></th>
            <th class="sort" data-type="badge">Tool / Top / Bot <span class="arrow">&#8597;</span></th>
            <th class="sort num" data-type="num">Rate @T1 <span class="arrow">&#8597;</span></th>
            <th class="sort num" data-type="num"><span id="c{t_index}-rh">{_rate_header(trial)}</span> <span class="arrow">&#8597;</span></th>
          </tr>
        </thead>
        <tbody>{roster_rows}</tbody>
      </table>
    </div>

    <h3>Tier timeline</h3>
    <div class="scroll">
      <table>
        <thead>
          <tr><th class=num>Tier</th><th class=num>Tier level</th>
              <th class=num>Effective target</th><th class=num>Party rate/s</th>
              <th class=num>Time to clear (s)</th><th class=num>Cumulative (s)</th>
              <th class=num>Progress</th><th>Result</th></tr>
        </thead>
        <tbody id="c{t_index}-tl">{_timeline_rows(trial)}</tbody>
      </table>
    </div>
  </section>"""
    return card_html, assign_entries


# Self-contained page behaviour: player search + generic column sorter. Kept as
# a plain string (single braces) so it can be dropped verbatim into the rendered
# HTML; it depends only on the embedded #assign-data JSON and data-* attributes.
_TRIALS_JS = r"""
(function () {
  "use strict";

  // ---------- Player search ----------
  var dataEl = document.getElementById("assign-data");
  var data = dataEl ? JSON.parse(dataEl.textContent) : [];
  var input = document.getElementById("member-search");
  var panel = document.getElementById("search-results");

  function jump(rowId) {
    var el = document.getElementById(rowId);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.remove("row-flash");
    void el.offsetWidth; // force reflow so the flash animation restarts
    el.classList.add("row-flash");
  }

  function clearPanel() {
    if (!panel) return;
    panel.hidden = true;
    while (panel.firstChild) panel.removeChild(panel.firstChild);
  }

  function renderResults(q) {
    q = q.trim().toLowerCase();
    while (panel.firstChild) panel.removeChild(panel.firstChild);
    if (!q) { panel.hidden = true; return; }
    var hits = data.filter(function (d) {
      return d.n.toLowerCase().indexOf(q) !== -1;
    }).slice(0, 12);
    panel.hidden = false;
    if (!hits.length) {
      var empty = document.createElement("div");
      empty.className = "sr-empty";
      empty.textContent = "No member matches that name.";
      panel.appendChild(empty);
      return;
    }
    hits.forEach(function (h) {
      // A row, not a button: it carries TWO controls (pin, jump), and a button
      // nested inside a button is invalid markup browsers flatten unpredictably.
      var item = document.createElement("div");
      item.className = "sr-item";
      item.appendChild(makeStar(h.n));

      var b = document.createElement("button");
      b.type = "button";
      b.className = "sr-jump";
      var name = document.createElement("span");
      name.className = "sr-name";
      name.textContent = h.n;
      var trial = document.createElement("span");
      trial.className = "sr-trial";
      trial.textContent = h.t;
      b.appendChild(name);
      b.appendChild(trial);
      b.addEventListener("click", function () {
        jump(h.r);
        input.value = h.n;
        clearPanel();
      });
      item.appendChild(b);
      panel.appendChild(item);
    });
    syncStars();
  }

  if (input && panel) {
    input.addEventListener("input", function () { renderResults(input.value); });
    input.addEventListener("focus", function () {
      if (input.value.trim()) renderResults(input.value);
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { clearPanel(); }
    });
    document.addEventListener("click", function (e) {
      if (e.target !== input && !panel.contains(e.target)) clearPanel();
    });
  }

  // ---------- Pinned members ----------
  // Most readers want one thing from this page: which trial am I in, and is it
  // safe? Pinning lifts that answer to the top and keeps it there on the next
  // visit, so the page opens on their own row instead of a wall of eight parties.
  //
  // Stored in localStorage under a key NAMESPACED BY GUILD. Both guild sites are
  // served from the one github.io origin and localStorage is per-origin, not
  // per-directory, so a bare "pins" key would have Survey Corps and Lactose
  // Intolerance silently overwrite each other. NAMES are stored, never row ids:
  // ids are regenerated on every weekly build and would point at a stranger by
  // Tuesday, whereas a name still resolves — or honestly fails to.
  var PIN_KEY = dataEl ? (dataEl.getAttribute("data-pin-key") || "") : "";
  var pinSection = document.getElementById("pinned-section");
  var pinList = document.getElementById("pinned-list");
  var pinClear = document.getElementById("pin-clear");

  // Every localStorage call is wrapped: it throws outright in Safari's private
  // mode and wherever site data is blocked, and a page that cannot remember pins
  // must still search, sort and render normally.
  function pinsRead() {
    if (!PIN_KEY) return [];
    var raw = null;
    try { raw = window.localStorage.getItem(PIN_KEY); } catch (e) { return []; }
    if (!raw) return [];
    try {
      var v = JSON.parse(raw);
      if (Object.prototype.toString.call(v) !== "[object Array]") return [];
      return v.filter(function (x) { return typeof x === "string" && x; });
    } catch (e) { return []; }
  }

  function pinsWrite(list) {
    if (!PIN_KEY) return;
    try { window.localStorage.setItem(PIN_KEY, JSON.stringify(list)); } catch (e) {}
  }

  function entryFor(name) {
    for (var i = 0; i < data.length; i++) {
      if (data[i].n === name) return data[i];
    }
    return null;
  }

  function makeStar(name) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "fav";
    b.setAttribute("data-fav", name);
    b.setAttribute("aria-pressed", "false");
    b.textContent = "☆";
    return b;
  }

  // One pass over every star on the page — in the roster tables, on the bench, in
  // the search panel and in the pinned list — so all of them agree after any
  // change, wherever the change was made.
  function syncStars() {
    var pinned = {};
    pinsRead().forEach(function (n) { pinned[n] = true; });
    var btns = document.querySelectorAll("button[data-fav]");
    Array.prototype.forEach.call(btns, function (b) {
      var name = b.getAttribute("data-fav");
      var on = pinned[name] === true;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.textContent = on ? "★" : "☆";
      var label = (on ? "Unpin " : "Pin ") + name;
      b.title = label;
      b.setAttribute("aria-label", label);
    });
  }

  function pinRow(name) {
    var e = entryFor(name);
    var row = document.createElement("div");
    row.className = e ? "pin" : "pin pin-stale";
    row.appendChild(makeStar(name));

    var who = document.createElement("span");
    who.className = "pin-name";
    who.textContent = name;
    row.appendChild(who);

    var trial = document.createElement("span");
    trial.className = "pin-trial";
    // A pin can outlive the member: someone leaves the guild, or the sheet spells
    // them differently this week. Say so and keep the row — silently dropping it
    // would read as "you were never pinned" and leave no way to tidy up.
    trial.textContent = e ? e.t : "not on this week's page";
    row.appendChild(trial);

    var detail = document.createElement("span");
    detail.className = "pin-detail";
    detail.textContent = e
      ? (e.d + (e.l ? " · level " + e.l : ""))
      : "No member of this name was in the roster when the page was built.";
    row.appendChild(detail);

    if (e && e.m) {
      var margin = document.createElement("span");
      margin.className = "pin-margin " + (e.b || "");
      margin.textContent = e.m;
      row.appendChild(margin);
    }

    if (e) {
      var go = document.createElement("button");
      go.type = "button";
      go.className = "pin-jump";
      go.textContent = "View row →";
      go.addEventListener("click", function () { jump(e.r); });
      row.appendChild(go);
    }
    return row;
  }

  function renderPins() {
    if (!pinSection || !pinList) { syncStars(); return; }
    var pins = pinsRead();
    while (pinList.firstChild) pinList.removeChild(pinList.firstChild);
    // Hidden entirely when empty rather than shown as a placeholder: a reader who
    // never pins anyone should not pay a box for the feature. The hint under the
    // search input is what advertises it.
    pinSection.hidden = pins.length === 0;
    pins.forEach(function (name) { pinList.appendChild(pinRow(name)); });
    syncStars();
  }

  function togglePin(name) {
    if (!name) return;
    var pins = pinsRead();
    var at = pins.indexOf(name);
    if (at === -1) pins.push(name); else pins.splice(at, 1);
    pinsWrite(pins);
    renderPins();
  }

  // Delegated, so it also catches the stars this script creates later — the ones
  // in the search panel and in the pinned list itself.
  document.addEventListener("click", function (e) {
    var btn = e.target && e.target.closest ? e.target.closest("button[data-fav]") : null;
    if (btn) togglePin(btn.getAttribute("data-fav"));
  });

  if (pinClear) {
    pinClear.addEventListener("click", function () { pinsWrite([]); renderPins(); });
  }

  // Keeps the level-1 and level-20 trials pages (and any other open tab on this
  // guild) in step, since they share the one key.
  window.addEventListener("storage", function (e) {
    if (!e.key || e.key === PIN_KEY) renderPins();
  });

  renderPins();

  // ---------- Generic sortable roster tables ----------
  function keyOf(row, col, type) {
    var cell = row.cells[col];
    if (!cell) return type === "text" ? "" : 0;
    var raw = cell.getAttribute("data-sort");
    var v = raw !== null ? raw : cell.textContent;
    if (type === "text") return v.trim().toLowerCase();
    var f = parseFloat(v);
    return isNaN(f) ? 0 : f;
  }

  function compare(a, b, col, type) {
    var x = keyOf(a, col, type), y = keyOf(b, col, type);
    if (type === "text") return x < y ? -1 : (x > y ? 1 : 0);
    if (type === "badge") return y - x; // checked-first
    return x - y;                       // numeric ascending
  }

  function setArrows(heads, col, asc, type) {
    for (var i = 0; i < heads.length; i++) {
      var ar = heads[i].querySelector(".arrow");
      if (!ar) continue;
      if (i === col) {
        // Arrow reflects visual order: largest / checked / z-first on top = down.
        var down = (type === "badge") ? asc : !asc;
        ar.textContent = down ? "▼" : "▲";
        ar.classList.add("active");
      } else {
        ar.textContent = "↕";
        ar.classList.remove("active");
      }
    }
  }

  function sortBy(table, heads, col, type, asc) {
    var tbody = table.tBodies[0];
    var rows = Array.prototype.slice.call(tbody.rows);
    rows.sort(function (a, b) {
      var c = compare(a, b, col, type);
      return asc ? c : -c;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
    table.__sortCol = col;
    table.__sortAsc = asc;
    setArrows(heads, col, asc, type);
  }

  var tables = document.querySelectorAll("table.sortable");
  Array.prototype.forEach.call(tables, function (table) {
    if (!table.tHead || !table.tHead.rows.length) return;
    var heads = Array.prototype.slice.call(table.tHead.rows[0].cells);
    heads.forEach(function (th, col) {
      if (!th.classList.contains("sort")) return;
      th.addEventListener("click", function () {
        var type = th.getAttribute("data-type") || "text";
        var asc = (table.__sortCol === col) ? !table.__sortAsc : true;
        sortBy(table, heads, col, type, asc);
      });
    });
    // Rows are already rendered in the default order (rate at the final tier,
    // descending) server-side, so just reflect that in the initial arrow.
    var def = table.getAttribute("data-default-sort");
    if (def !== null) {
      var dcol = parseInt(def, 10);
      var dtype = heads[dcol] ? (heads[dcol].getAttribute("data-type") || "num") : "num";
      table.__sortCol = dcol;
      table.__sortAsc = false; // descending
      setArrows(heads, dcol, false, dtype);
    }
    // Re-apply whatever sort is currently in force. The buff-level selector
    // rewrites the rate cells underneath the reader, and a table sorted by a
    // column whose values have just changed is no longer sorted at all. Honours
    // the reader's own choice of column rather than yanking them back to the
    // default: only the ORDER is refreshed, never the criterion.
    table.__resort = function () {
      var col = table.__sortCol;
      if (col === undefined || col === null) return;
      var th = heads[col];
      var type = th ? (th.getAttribute("data-type") || "num") : "num";
      sortBy(table, heads, col, type, table.__sortAsc);
    };
  });

  // ---------- Community-buff level selector ----------
  // ONE optimiser run, rated at every rung of the game's 1..20 ladder at BUILD
  // time and shipped inline in #levels-data. Nothing here models anything: it
  // swaps prepared text into prepared slots, which is why the page still works
  // from a file:// checkout and off the network. What the rungs mean — and the
  // fact that they are a LOWER bound, the parties being fixed — is spelled out
  // in build._render_buff_slider and on the page itself.
  var lvlEl = document.getElementById("levels-data");
  var LEVELS = null;
  try {
    LEVELS = lvlEl ? JSON.parse(lvlEl.textContent) : null;
  } catch (e) { LEVELS = null; }
  var lvlBox = document.getElementById("buff-level");
  var lvlRange = document.getElementById("buff-range");

  if (LEVELS && lvlBox && lvlRange) {
    var PUBLISHED = lvlBox.getAttribute("data-published") || "";
    var stripEl = document.getElementById("strip");
    var resetBtn = document.getElementById("buff-reset");

    function put(id, markup) {
      var el = document.getElementById(id);
      if (el) el.innerHTML = markup;
    }

    function rowsHtml(cells) {
      var out = "";
      for (var r = 0; r < cells.length; r++) {
        var row = cells[r];
        out += '<tr class="' + (row[7] === "cleared" ? "cleared" : "failed") + '">';
        for (var j = 0; j < 7; j++) out += "<td class=num>" + row[j] + "</td>";
        out += "<td>" + row[7] + "</td></tr>";
      }
      return out;
    }

    function applyLevel(level) {
      var rung = LEVELS[String(level)];
      if (!rung) return;
      if (stripEl) stripEl.innerHTML = rung.strip;
      for (var t = 0; t < rung.cards.length; t++) {
        var c = rung.cards[t];
        put("c" + t + "-head", c.head);
        put("c" + t + "-safe", c.safe);
        // Only when the server emitted the slot: a card with no marginal-seat
        // line at the published level has none at any level (the phrase is empty
        // only for a party with no usable rates, which no buff can change).
        if (c.marg) put("c" + t + "-marg", c.marg);
        put("c" + t + "-rh", c.rh);
        // Rates are addressed by the row id the server assigned, NEVER by the
        // row's position: the reader may have re-sorted the table, and writing
        // by position would put each member's rate in a stranger's row.
        for (var i = 0; i < c.rates.length; i++) {
          var tr = document.getElementById("r-" + t + "-" + i);
          if (!tr || tr.cells.length < 5) continue;
          for (var k = 0; k < 2; k++) {
            var cell = tr.cells[3 + k];
            cell.textContent = c.rates[i][k];
            cell.setAttribute("data-sort", c.rates[i][k]);
          }
        }
        put("c" + t + "-tl", rowsHtml(c.tl));
      }
      // The search index denormalises each trial's score and margin onto every
      // member in it, so it moves with the level too — otherwise a pinned member
      // would read the published figures inside a raised-buff view.
      for (var d = 0; d < data.length; d++) {
        var s = rung.assign[data[d].t];
        if (s) { data[d].d = s[0]; data[d].m = s[1]; data[d].b = s[2]; }
      }
      renderPins();
      if (input && panel && !panel.hidden) renderResults(input.value);

      var off = String(level) !== String(PUBLISHED);
      put("buff-level-num", String(level));
      put("buff-mags", rung.note);
      put("buff-off-num", String(level));
      var offEl = document.getElementById("buff-off");
      if (offEl) offEl.hidden = !off;
      if (resetBtn) resetBtn.hidden = !off;
      if (stripEl) {
        if (off) stripEl.classList.add("off-level");
        else stripEl.classList.remove("off-level");
      }
      Array.prototype.forEach.call(
        document.querySelectorAll("table.sortable"),
        function (table) { if (table.__resort) table.__resort(); }
      );
    }

    function levelFromHash() {
      var m = /(?:^|[#&])buffs=(\d+)/.exec(window.location.hash || "");
      return m && LEVELS[m[1]] ? m[1] : null;
    }

    // The chosen level lives in the URL and NOT in localStorage, deliberately.
    // A remembered level would have a reader return next week to numbers that are
    // not the published plan, with nothing on screen to say when they chose them;
    // in the URL it is visible, shareable, and gone the moment they open the page
    // afresh. (Pins are remembered because a pin is about the reader; a buff level
    // is about the guild.)
    lvlRange.addEventListener("input", function () {
      applyLevel(lvlRange.value);
      try {
        window.history.replaceState(
          null, "",
          lvlRange.value === PUBLISHED ? "#" : "#buffs=" + lvlRange.value
        );
      } catch (e) {}
    });
    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        lvlRange.value = PUBLISHED;
        applyLevel(PUBLISHED);
        try { window.history.replaceState(null, "", "#"); } catch (e) {}
      });
    }
    window.addEventListener("hashchange", function () {
      var h = levelFromHash() || PUBLISHED;
      lvlRange.value = h;
      applyLevel(h);
    });
    var initial = levelFromHash();
    if (initial && initial !== PUBLISHED) {
      lvlRange.value = initial;
      applyLevel(initial);
    }
  }
})();
"""


# A human-friendly name for each optimizer strategy token (see src/optimizer.py).
_STRATEGY_NAMES = {
    "random": "random split",
    "proxy_greedy": "greedy (rate proxy)",
    "marginal_greedy": "greedy (marginal points)",
    "beam": "beam search",
    "genetic": "genetic algorithm",
    "hill_climb": "hill-climbing",
    "sa": "simulated annealing",
}


def _strategy_phrase(strategy: str) -> str:
    """Turn a strategy string like ``"marginal_greedy+hill_climb"`` into prose."""
    if strategy in ("best", "ensemble"):
        return "ensemble (best of several strategies)"
    parts = [_STRATEGY_NAMES.get(tok, tok) for tok in strategy.split("+") if tok]
    if not parts:
        return "assignment"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} refined by {' then '.join(parts[1:])}"


def _assignment_label(week: dict) -> str:
    """Short header chip: e.g. ``"optimised: greedy … , Phase 2"``."""
    strategy = week.get("strategy", "random")
    if strategy == "random":
        return "random assignment, Phase 1"
    return f"optimised: {_strategy_phrase(strategy)}, Phase 2"


def _assignment_detail(week: dict) -> str:
    """Sub-header line describing how parties were formed."""
    strategy = week.get("strategy", "random")
    if strategy == "random":
        return f"random split (seed {week['seed']}, cap {week['cap']})"
    return (
        f"optimised assignment via {_strategy_phrase(strategy)} "
        f"(cap {week['cap']}) &middot; {week['total_points']} guild points"
    )


def _assignment_footnote(week: dict) -> str:
    """Footer caveat describing the assignment method."""
    strategy = week.get("strategy", "random")
    if strategy == "random":
        return (
            "Random assignment, no optimizer. Parties are a plain seeded random "
            f"split (seed {week['seed']}) with no eligibility filtering."
        )
    return (
        f"Optimised assignment (Phase 2). Parties are chosen by {_strategy_phrase(strategy)} "
        "to maximise total guild points against the simulate_race model, honouring "
        f"the {week['cap']}-per-party cap; members who would only lower a party's tier are benched."
    )


def _guild_buildings_footnote(week: dict) -> str:
    """Footer line stating this week's guild-building skill-level contributions.

    Guild buildings are guild-wide (+2 skill levels per building level to every
    member), quite unlike the per-member house rooms. Rendered from the live
    ``guild_building_levels`` map so an unbuilt guild reads as an explicit zero
    rather than a silent omission.
    """
    granted = week.get("guild_building_levels") or {}
    active = {sk: lv for sk, lv in granted.items() if lv}
    if not active:
        return (
            "no skilling guild building is built, so BuildingSkillLevels = 0 for "
            "every trial this week"
        )
    return "this week " + ", ".join(
        f"<strong>{html.escape(sk)} +{lv}</strong>" for sk, lv in active.items()
    )


def _gp(value) -> str:
    """Whole guild points with thousands separators; em dash for None."""
    if value is None:
        return "&mdash;"
    return f"{value:,}"


def _cp(value) -> str:
    """Credit points to ONE decimal with thousands separators; em dash for None.

    Points became a FLOAT with the 2026-08-11 partial-credit patch: ``credit_points``
    carries the part-finished tier as well as the banked ones, so raw interpolation
    prints ``4940.365999999999``. One decimal is the honest resolution — a whole tier of
    partial credit is worth only ``TRIAL_PARTIAL_CREDIT_RATE * 100`` points, so a tenth
    of a point is already well inside the noise of the model's own constants, and any
    more digits would imply a precision the race does not have.

    Deliberately separate from :func:`_gp`, which stays integral: guild points SPENT on
    a building or a shrine are whole numbers from the game's own cost ladder, whereas
    points EARNED are now continuous.
    """
    if value is None:
        return "&mdash;"
    return f"{value:,.1f}"


def _payback(value) -> str:
    """A payback figure (draws or weeks): one decimal, em dash when it never pays.

    Big numbers lose the decimal — 3 significant-ish figures is generous for a
    payback measured in years, and the column stays narrow.
    """
    if value is None:
        return "&mdash;"
    return f"{value:,.0f}" if value >= 100 else f"{value:,.1f}"


def _render_upgrades_section(week: dict) -> str:
    """Bottom-of-page section: what does the next tier cost, and when does it pay?

    Reads the ``building_upgrades`` probes computed by
    ``trials.probe_building_upgrade`` — one per drawn skill, each carrying the
    number of building levels needed to gain a tier, the cumulative guild-point
    cost of those levels, and how long that spend takes to earn itself back. Rows
    are ordered by payback (soonest first, which is the officers' actual decision
    order); buildings that cannot reach another tier even at the level-20 cap are
    summarised in one line so the reader can see they were checked rather than
    omitted.
    """
    upgrades = week.get("building_upgrades") or []
    if not upgrades:
        return ""

    priced = sorted(
        (u for u in upgrades if u.get("reachable")),
        # Soonest payback first; unpriceable paybacks (None) sort last, and cost
        # breaks ties between equal paybacks.
        key=lambda u: (
            u["weeks_to_return"] if u.get("weeks_to_return") is not None
            else float("inf"),
            u.get("total_cost") or 0,
        ),
    )
    unreachable = [u for u in upgrades if not u.get("reachable")]
    weeks_between = config.TRIAL_WEEKS_BETWEEN_DRAWS

    if priced:
        rows = "".join(
            "<tr>"
            f"<th>{html.escape(u['building'])}</th>"
            f"<td>{html.escape(u['skill'])}</td>"
            f"<td class=num>+{u['levels_needed']}</td>"
            f"<td class=num>{u['from_level']} &rarr; {u['to_level']}</td>"
            f"<td class=num>+{u['skill_levels_after'] - u['skill_levels_now']} lv</td>"
            f"<td class=num>{u['tier_now']} &rarr; <strong>{u['tier_after']}</strong></td>"
            f"<td class=num>+{u['points_gained']}</td>"
            f"<td class=num>{_gp(u['total_cost'])}</td>"
            f"<td class=num>{_payback(u['draws_to_return'])}</td>"
            f"<td class=num><strong>{_payback(u['weeks_to_return'])}</strong></td>"
            "</tr>"
            for u in priced
        )
        body = f"""
    <p class="meta">{len(priced)} of {len(upgrades)} building(s) can buy another
       tier within the level-20 cap, soonest payback first. <strong>Levels</strong>
       is how many upgrades it takes; <strong>cost</strong> is all of those steps
       added together, from the game's own <code>guildPointCosts</code>.</p>
    <div class="scroll">
      <table>
        <thead><tr>
          <th>Building</th><th>Trial</th><th class=num>Levels</th>
          <th class=num>Building lv</th><th class=num>Grants</th>
          <th class=num>Tier</th><th class=num>Points</th>
          <th class=num>Total cost (gp)</th>
          <th class=num>Draws to repay</th><th class=num>Weeks to repay</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""
    else:
        body = """
    <p><strong>No building can buy another tier this week, at any level.</strong>
       Every drawn trial clears the same tier even with its building maxed, so the
       guild points are better banked (or spent on a building whose skill is drawn
       in a later week).</p>"""

    if unreachable:
        rejected = ", ".join(
            f"{html.escape(u['building'])} "
            + (
                "(already at the level cap)"
                if u.get("at_cap")
                else f"(no gain even at level {config.GUILD_BUILDING_MAX_LEVEL}, "
                f"still tier {u['tier_now']})"
            )
            for u in unreachable
        )
        body += f'\n    <p class="meta">Checked and rejected: {rejected}.</p>'

    return f"""
  <section class="card" id="upgrades-section">
    <h2>Guild building upgrades &mdash; what does the next tier cost?</h2>
    <p class="meta">For each of this week's trials, the race is re-run with its own
       guild building one level higher, then higher again, until the party clears
       another tier (each level grants <code>+2</code> skill levels to every member
       of that party). The table gives the cheapest such climb, its total
       guild-point cost, and how long that spend takes to earn itself back:
       one extra tier is worth <code>+{config.TRIAL_POINTS_PER_TIER}</code> points
       every time the trial runs, and any one skill is drawn about every
       <code>{weeks_between:g}</code> weeks (four of the ten skills per week), so
       <code>weeks = cost / points &times; {weeks_between:g}</code>.</p>
    <p class="meta">Two caveats, both deliberate. The payback assumes the bought
       tier is earned <em>every</em> time the skill is drawn &mdash; optimistic, since
       the roster, the sign-ups and the community buffs all move week to week.
       Against that, parties are held fixed here, so the levels needed are an
       <em>upper bound</em>: re-optimising the assignment afterwards could reach the
       tier sooner, never later. Buildings whose skill is not drawn this week cannot
       affect these numbers at all.</p>{body}
  </section>
"""


def _render_shrines_section(week: dict) -> str:
    """Guild shrines: what they grant every member today, and what one level more costs.

    Deliberately a SEPARATE card from the buildings, because a shrine is a different
    kind of purchase and pricing it the buildings' way understates it by roughly an
    order of magnitude: a building buffs one skill, so it only earns anything in the
    weeks that skill is drawn (every ``TRIAL_WEEKS_BETWEEN_DRAWS`` weeks), whereas a
    shrine buffs efficiency or action speed for everyone in every skill and therefore
    pays in ALL FOUR trials EVERY week. Hence no draw-frequency discount here, and a
    "gain per week" column rather than a per-draw one.

    Rows whose gain is exactly zero are the loot and XP shrines. They are rendered
    greyed rather than dropped, so the reader can see they were considered and priced at
    nothing — the same contract the buildings' "checked and rejected" line honours.
    """
    upgrades = week.get("shrine_upgrades") or []
    speed = week.get("shrine_speed") or 0.0
    efficiency = week.get("shrine_efficiency") or 0.0
    levels = week.get("guild_shrine_levels") or {}
    if not upgrades and not levels:
        return ""

    # Same order as the buildings' table for the same reason: soonest payback first is
    # the officers' actual decision order. Priceless rows (no gain, or at the cap) sort
    # last, and the loot/XP shrines land there by construction.
    ranked = sorted(
        upgrades,
        key=lambda u: (
            u["weeks_to_return"] if u.get("weeks_to_return") is not None
            else float("inf"),
            u.get("next_level_cost") or 0,
        ),
    )

    rows = []
    for u in ranked:
        gain = u.get("points_gained") or 0.0
        # A shrine that does not feed the race at all: say WHICH currency it pays in
        # instead, from the buff the game itself names, so "0" never reads as "broken".
        if gain == 0.0:
            note = "XP only" if u.get("buff") == "wisdom" else "loot only"
            if u.get("at_cap"):
                note = "at the level cap"
            rows.append(
                "<tr class=dim>"
                f"<th>{html.escape(u.get('name') or u.get('shrine') or '?')}</th>"
                f"<td>{html.escape(u.get('buff') or '?')}</td>"
                f"<td class=num>{u.get('from_level', 0)}</td>"
                f"<td class=num>{_gp(u.get('next_level_cost'))}</td>"
                f"<td class=num>&mdash;</td>"
                f"<td class=num>{note}</td>"
                "</tr>"
            )
            continue
        rows.append(
            "<tr>"
            f"<th>{html.escape(u.get('name') or u.get('shrine') or '?')}</th>"
            f"<td>{html.escape(u.get('buff') or '?')}</td>"
            f"<td class=num>{u.get('from_level', 0)}</td>"
            f"<td class=num>{_gp(u.get('next_level_cost'))}</td>"
            f"<td class=num>+{_cp(gain)}</td>"
            f"<td class=num><strong>{_payback(u.get('weeks_to_return'))}</strong></td>"
            "</tr>"
        )

    table = f"""
    <div class="scroll">
      <table>
        <thead><tr>
          <th>Shrine</th><th>Buff</th><th class=num>Level</th>
          <th class=num>Next level (gp)</th><th class=num>Gain/week</th>
          <th class=num>Weeks to repay</th>
        </tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>""" if rows else ""

    built = ", ".join(
        f"<strong>{html.escape(config.GUILD_SHRINE_NAMES.get(k, k))} lv {lv}</strong>"
        for k, lv in levels.items() if lv
    ) or "none built"

    return f"""
  <section class="card" id="shrines-section">
    <h2>Guild shrines &mdash; the buff every member carries into every trial</h2>
    <p class="meta">Since the 2026-08-11 patch the shrine buffs apply inside guild
       trials, so every member of every party this week runs with
       <code>+{efficiency * 100:.1f}%</code> efficiency and
       <code>+{speed * 100:.1f}%</code> action speed on top of their own gear and house.
       Levels in place: {built}. Unlike a guild building, which grants skill levels in
       <em>one</em> skill and therefore earns nothing in the weeks that skill is not
       drawn, a shrine pays in <strong>all four trials, every week</strong> &mdash; so
       the payback below carries no draw-frequency discount.</p>
    <p class="meta">And yet the verdict is that <strong>buildings dominate shrines as an
       investment</strong>. The shrine guild-point ladder is exactly <em>double</em> the
       buildings' at every level, while the measured effect of one level is a fraction of
       a tier spread across four parties, so the payback runs far longer than any
       building's on this page. The gain is only priceable at all because of partial-tier
       credit: under the old step objective one shrine level almost never crossed a tier
       boundary anywhere, so it scored exactly zero in every trial and the upgrade could
       not be valued. Parties are held fixed here, exactly as in the buildings' table, so
       each gain is a lower bound and each payback an upper bound.</p>{table}
  </section>
"""


def _render_min_levels_section(week: dict) -> str:
    """The per-trial minimum sign-up level: what is set, and what would match the model.

    The patch gave officers a per-trial minimum sign-up level. Read as a constraint it
    is a nuisance; read as a LEVER it is the thing this tool has never had — the model
    has always been able to say "these members should sit this one out" and an officer
    has never had any way to make that happen. ``suggested`` is simply the lowest level
    the optimizer actually seated, so setting it excludes exactly the members the model
    already declined to pick and nobody else.

    The two exclusion counts are the whole point of the table. Where ``would_exclude``
    equals ``already_benched`` the setting merely formalises a bench the model had
    already chosen; where it is larger, it would bar members this week's model was happy
    to seat, and it is then a trade rather than a tidy-up.
    """
    advice = week.get("min_level_advice") or []
    if not advice:
        return ""

    rows = []
    for a in advice:
        current = a.get("current")
        suggested = a.get("suggested")
        exclude = a.get("would_exclude") or 0
        benched = a.get("already_benched") or 0
        extra = exclude - benched
        if suggested is None:
            verdict = "no seated member reports a level, so nothing can be suggested"
            band = "warn-text"
        elif extra <= 0:
            verdict = (
                f"formalises a bench the model already chose &mdash; all {exclude} "
                f"excluded were benched anyway"
            )
            band = "ok-text"
        else:
            verdict = (
                f"would bar {extra} member(s) the model was happy to seat "
                f"({exclude} excluded, {benched} already benched)"
            )
            band = "warn-text"
        rows.append(
            "<tr>"
            f"<th>{html.escape(a.get('skill') or '?')}</th>"
            f"<td class=num>{'&mdash;' if current is None else current}</td>"
            f"<td class=num><strong>"
            f"{'&mdash;' if suggested is None else suggested}</strong></td>"
            f"<td class=num>{a.get('party_size') or 0}</td>"
            f"<td class=num>{exclude}</td>"
            f"<td class=num>{benched}</td>"
            f'<td class="{band}">{verdict}</td>'
            "</tr>"
        )

    return f"""
  <section class="card" id="min-levels-section">
    <h2>Minimum sign-up level &mdash; what the officers set, and what would match this plan</h2>
    <p class="meta"><strong>Set in game</strong> is the minimum this week's
       <em>Trial Priority</em> block records for each trial (an em dash where none is
       set); <strong>would match</strong> is the lowest level the optimizer actually
       seated, i.e. the number that reproduces the party below and excludes nobody
       else. It is advice, not an instruction: a minimum also bars members from
       volunteering in future weeks, and it cannot tell "too weak to help" apart from
       "too weak to help <em>this</em> week alongside these particular twenty-odd".</p>
    <div class="scroll">
      <table>
        <thead><tr>
          <th>Trial</th><th class=num>Set in game</th><th class=num>Would match</th>
          <th class=num>Party</th><th class=num>Excludes</th>
          <th class=num>Already benched</th><th>Effect</th>
        </tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
  </section>
"""


def _expected_total_note(total_credit, total_expected) -> str:
    """`` &middot; 4,947.2 expected`` for a strip tile, or "" when it adds nothing.

    Suppressed when the two agree within half a point, which is the comfortable case:
    the expectation only diverges where a tier is being held by seconds, and that is
    exactly when an officer needs to see it.
    """
    if total_expected is None or total_credit is None:
        return ""
    if abs(total_credit - total_expected) < 0.5:
        return ""
    return f" &middot; <strong>{_cp(total_expected)} expected</strong>"


def _deterministic_total_note(total_objective, total_credit) -> str:
    """`` &middot; 4,939.9 deterministic`` for a strip tile, or "" when it adds nothing.

    The mirror of :func:`_expected_total_note`, for the page whose headline is already
    the expectation (see ``config.OPT_OBJECTIVE``). Same suppression rule and the same
    reason for it: the two figures only diverge where a tier is being held by seconds,
    and printing both on a comfortable lineup is noise. What differs is which one is
    the aside.
    """
    if total_credit is None or total_objective is None:
        return ""
    if abs(total_credit - total_objective) < 0.5:
        return ""
    return f" &middot; <strong>{_cp(total_credit)} deterministic</strong>"


def _render_buff_toggle(week: dict, counterpart: Optional[dict]) -> str:
    """The community-buff level switch: two segments, this page's one active.

    The whole page — every party, tier, rate and total — is one optimiser run at
    ONE community-buff level, so the switch cannot recompute anything in the
    browser; it navigates to the sibling page that was built under the other
    regime. Both segments carry their own credit total, so the reader learns what
    the other view is worth *before* clicking, and the delta is legible without
    holding a number in their head.

    ``counterpart`` is ``{"href", "level", "total"}`` for the sibling page, or
    ``None`` (a lone page, e.g. a pre-existing ``trials.json`` re-render) in which
    case no switch is emitted at all.
    """
    if not counterpart:
        return ""
    # Falsy covers both cases that mean "no regime recorded": a pre-buff trials.json
    # with the key missing, and a WeekResult built by hand at the dataclass default
    # of 0 (run_week never records 0 — the ladder clamps to 1).
    here_level = week.get("community_buff_level")
    if not here_level:
        return ""
    here_total = week.get("total_credit_points") or week.get("total_points")
    segments = [
        (here_level, here_total, None),
        (counterpart["level"], counterpart.get("total"), counterpart["href"]),
    ]
    # Lowest level first, so the pair never swaps sides between the two pages —
    # a control whose halves move when you click it reads as two controls.
    segments.sort(key=lambda s: s[0])
    parts = []
    for level, total, href in segments:
        label = f"Level {level}<span class=bt-pts>{_cp(total)} pts</span>"
        if href is None:
            parts.append(f'<span class="bt-seg active" aria-current="page">{label}</span>')
        else:
            parts.append(f'<a class="bt-seg" href="{html.escape(href)}">{label}</a>')
    delta = None
    if here_total is not None and counterpart.get("total") is not None:
        delta = counterpart["total"] - here_total
    note = (
        f"Every number on this page is modelled with all three community buffs at "
        f"<strong>ladder level {here_level}</strong> "
        f"({_pct(week.get('community_buff_gathering'))} gathering, "
        f"{_pct(week.get('community_buff_production'))} production efficiency, "
        f"{_pct(week.get('community_buff_enhancing'))} enhancing speed). "
        f"Level {counterpart['level']} is a SEPARATE, full optimiser run &mdash; the "
        f"parties it seats may differ, not merely their rates"
    )
    if delta is not None:
        note += (
            f", and it is worth <strong>{_cp(abs(delta))} points "
            f"{'more' if delta >= 0 else 'less'}</strong> across the week"
        )
    return f"""
  <div class="bufftoggle" role="group" aria-label="Community buff level">
    <span class="bt-label">Community buffs</span>
    <span class="bt-segs">{''.join(parts)}</span>
  </div>
  <p class="bt-note">{note}.</p>"""


def _buff_ladder_payload(week: dict, ladder: dict) -> dict:
    """Every rung of the community-buff ladder, as the fragments the page swaps.

    ``ladder`` is ``{level: WeekResult dict}`` from ``trials.run_week_ladder`` — one
    optimiser run rated at each level, so every rung seats the same members in the
    same trials and only the numbers move.

    THE ROW ORDER IS THE PUBLISHED ONE, AND MUST BE. Roster rows carry the DOM ids
    ``r-<trial>-<index>`` assigned by ``_render_trial_card`` from
    ``_sorted_roster(published trial)``. A rung sorted by its OWN rates would put a
    different member at each index and the selector would write everyone's rate into
    somebody else's row, so each rung is re-indexed by NAME against the published
    order before it ships.

    Rates ship as their DISPLAY strings and the page uses them for the sort key too.
    That is sound only because a single member's rate runs at 5-50 work/second and
    never reaches the thousands separator ``_num`` would insert (a whole PARTY's rate
    does, which is why the timeline keeps its own formatting); the cost is that
    sorting the roster after a level change compares two decimals rather than
    seventeen, which can reorder members whose rates agree to 0.005.
    """
    payload: dict = {}
    for level, rung in ladder.items():
        cards = []
        for t_index, rung_trial in enumerate(rung["trials"]):
            published_trial = week["trials"][t_index]
            by_name = {r["name"]: r for r in rung_trial["roster"]}
            rates = []
            for r in _sorted_roster(published_trial):
                other = by_name.get(r["name"], r)
                rates.append([_num(other["rate_tier1"]), _num(other["rate_final"])])
            cards.append(
                {
                    "head": _card_headline(rung_trial),
                    "safe": _card_safety(rung_trial),
                    "marg": _marginal_seat_phrase(rung_trial, week["cap"]),
                    "rh": _rate_header(rung_trial),
                    "rates": rates,
                    "tl": _timeline_cells(rung_trial),
                }
            )
        payload[str(level)] = {
            "strip": _stat_strip(rung),
            "cards": cards,
            # Keyed by trial NAME, not index: the search index entries carry the
            # skill (``t``) and the bench entries carry the literal "Bench", so a
            # name lookup needs no parallel ordering to stay correct.
            "assign": {
                t["skill"]: list(_assign_summary(t)) for t in rung["trials"]
            },
            "note": _buff_level_note(rung),
        }
    return payload


def _buff_level_note(week: dict) -> str:
    """One line naming the three magnitudes a rung actually ran on."""
    return (
        f"{_pct(week.get('community_buff_gathering'))} gathering &middot; "
        f"{_pct(week.get('community_buff_production'))} production efficiency "
        f"&middot; {_pct(week.get('community_buff_enhancing'))} enhancing speed"
    )


def _render_buff_slider(week: dict, ladder: Optional[dict]) -> str:
    """The community-buff level selector: one plan, twenty ratings of it.

    Unlike ``_render_buff_toggle`` — which navigates between two pages because each
    was a separate optimiser run — this control recomputes nothing and fetches
    nothing. Every rung was rated at build time by ``trials.run_week_ladder`` and
    ships inline, so moving it is a DOM swap; the page therefore works from a
    ``file://`` checkout and with no network at all, which a fetch would not.

    WHAT THE READER MUST UNDERSTAND, and why the caveat is in the control rather
    than in a footnote: the parties do not move. Every rung says what THIS WEEK'S
    PLAN would score at that level, which is a floor under what the guild could
    score there — at a raised buff the optimiser would seat different members and
    do at least as well. Overstating that would turn a lower bound into a forecast.

    Returns "" when there is no ladder (the switch is off, or a lone re-render of an
    old trials.json), so the page falls back to exactly what it was before.
    """
    if not ladder:
        return ""
    published = week.get("community_buff_level")
    if not published:
        return ""
    levels = sorted(int(k) for k in ladder)
    lo, hi = levels[0], levels[-1]
    return f"""
  <div class="bufflevel" id="buff-level" data-published="{published}">
    <div class="bl-row">
      <label class="bl-label" for="buff-range">Community buffs</label>
      <input id="buff-range" class="bl-range" type="range" min="{lo}" max="{hi}"
             step="1" value="{published}" list="buff-ticks"
             aria-describedby="buff-readout">
      <datalist id="buff-ticks">{
        "".join(f'<option value="{n}"></option>' for n in levels)
      }</datalist>
      <span class="bl-readout" id="buff-readout" aria-live="polite">
        <strong>Level <span id="buff-level-num">{published}</span></strong>
        <span class="bl-mag" id="buff-mags">{_buff_level_note(week)}</span>
      </span>
      <button type="button" class="bl-reset" id="buff-reset" hidden>
        back to level {published}</button>
    </div>
    <p class="bl-note">Every number on this page is modelled with all three
       community buffs at <strong>ladder level {published}</strong>, the level the
       site publishes because the guild's real levels are in no capture this repo
       holds. Moving the slider re-rates <em>this same plan</em> at another level
       &mdash; the parties never change, so what you see is a <strong>lower
       bound</strong> on that level: with better buffs the optimiser would seat
       different members and score at least as much.
       <span class="bl-off" id="buff-off" hidden>Showing level
       <strong><span id="buff-off-num">{published}</span></strong>, not the
       published plan.</span></p>
  </div>"""


def _render_trials_html(
    week: dict,
    site: "GuildSite",
    draw_warning: str = "",
    counterpart: Optional[dict] = None,
    ladder: Optional[dict] = None,
) -> str:
    """Render the full trials page from a ``WeekResult`` dict.

    ``draw_warning``, when set, is shown as a banner at the top of the page: the
    live draw could not be read and the skills below are the last known ones (see
    ``_load_draw``). Empty means the draw came from the sheet as normal.

    ``counterpart`` names the sibling page built under the OTHER community-buff
    level (``{"href", "level", "total"}``) and turns on the level switch at the top
    of the page; ``None`` renders the page alone, exactly as before. See
    ``_render_buff_toggle``.

    ``ladder`` is ``{level: WeekResult dict}`` for the SAME plan rated at every
    community-buff level (``trials.run_week_ladder``) and turns on the level
    selector; ``None`` omits it and every number on the page is the published
    level's, as it was before the selector existed. The two controls are
    independent and may both be on: the toggle navigates to a differently-OPTIMISED
    page, the selector re-rates this one.
    """
    strip = _stat_strip(week)

    cards_parts: list[str] = []
    assign_index: list[dict] = []
    for t_index, t in enumerate(week["trials"]):
        card_html, entries = _render_trial_card(t, t_index, week["cap"])
        cards_parts.append(card_html)
        assign_index.extend(entries)
    cards = "".join(cards_parts)

    bench = week["bench"]
    # Chips rather than a comma list, so a benched member can pin themselves too —
    # "am I in this week?" is exactly the question the bench answers, and it is
    # worth an answer at the top of the page like any other.
    bench_html = (
        " ".join(
            f'<span class="bench-name">{_fav_button(n)}{html.escape(n)}</span>'
            for n in bench
        )
        if bench
        else "(none)"
    )
    # Bench members jump to the bench section (they have no roster row).
    assign_index.extend(
        {
            "n": n, "t": "Bench", "r": "bench-section", "l": None,
            "d": "Not assigned to a trial this week", "m": "", "b": "",
        }
        for n in bench
    )

    # Embedded, self-contained assignment data for the player search. Escape
    # "<" so the JSON can never break out of the <script> element.
    assign_json = json.dumps(assign_index, ensure_ascii=False).replace(
        "<", "\\u003c"
    )

    upgrades_section = _render_upgrades_section(week)
    shrines_section = _render_shrines_section(week)
    min_levels_section = _render_min_levels_section(week)
    buff_toggle = _render_buff_toggle(week, counterpart)
    buff_slider = _render_buff_slider(week, ladder)
    # The ladder ships as a SECOND inline JSON island rather than inside #assign-data,
    # because the search index is read on every keystroke and the ladder only when the
    # selector moves. Same "<" escape, same reason: neither may break out of its
    # <script> element. Empty (and the island omitted) when there is no selector.
    levels_json = (
        json.dumps(
            _buff_ladder_payload(week, ladder), ensure_ascii=False
        ).replace("<", "\\u003c")
        if buff_slider
        else ""
    )
    levels_script = (
        f'<script id="levels-data" type="application/json">{levels_json}</script>'
        if buff_slider
        else ""
    )

    # The raised-buff page is a COUNTERFACTUAL and must never be mistaken for the
    # published plan, so it says so in the tab title and the headline as well as in
    # the switch. "Raised" is decided against the sibling page rather than against
    # config, because the default level is a config value the switch itself exists
    # to step away from.
    buff_level = week.get("community_buff_level") or 0
    is_raised = bool(counterpart) and buff_level > counterpart["level"]
    title_suffix = f" (community buffs L{buff_level})" if is_raised else ""
    buff_h1 = (
        f' <span class="meta">&middot; community buffs L{buff_level}</span>'
        if is_raised
        else ""
    )
    json_name = TRIALS_MAXBUFF_JSON if is_raised else TRIALS_JSON
    # Only claim a control exists when one was actually emitted: a lone render must
    # not promise the reader something that is not on the page. The two controls make
    # DIFFERENT promises and the footnote has to keep them apart — the selector
    # re-rates these parties, the switch replaces them.
    switch_phrase = (
        " &mdash; and the switch at the top of the page shows the same week "
        f"optimised again at level {counterpart['level']}"
        if buff_toggle
        else ""
    )
    if buff_slider:
        switch_phrase += (
            " &mdash; and the selector at the top of the page re-rates <em>this same "
            "plan</em> at every rung of the ladder, which is a lower bound at each "
            "one, the parties being held fixed"
        )

    # Stale-draw banner: deliberately the first thing on the page, so a fallback
    # draw can never be mistaken for a live one.
    alert_html = (
        '<div class="alert" role="alert"><strong>Draw may be stale.</strong> '
        f"{html.escape(draw_warning)}</div>"
        if draw_warning
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(site.title)} - Guild Trials{title_suffix}</title>
<style>
  :root {{
    --bg: #0f1115; --panel: #171a21; --line: #2a2f3a;
    --text: #e6e8ec; --muted: #99a0ad; --accent: #6ea8fe;
    --on: #3ecf8e; --off: #3a3f4b; --warn: #e0b341; --danger: #f5645a;
  }}
  /* Risk bands, shared with the sign-up page so one lineup never reads as two
     different colours across the site. */
  .ok-text {{ color: var(--on); }}
  .warn-text {{ color: var(--warn); }}
  .danger-text {{ color: var(--danger); font-weight: 700; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 2rem 1.25rem 4rem;
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text);
  }}
  header, main, footer {{ max-width: 1100px; margin-left: auto; margin-right: auto; }}
  header {{ margin-bottom: 1.5rem; }}
  h1 {{ margin: 0 0 .25rem; font-size: 1.6rem; letter-spacing: .5px; }}
  h2 {{ font-size: 1.15rem; margin: 0 0 .3rem; color: var(--accent); }}
  h3 {{ font-size: .95rem; margin: 1.1rem 0 .5rem; color: var(--muted);
        text-transform: uppercase; letter-spacing: .4px; }}
  .meta {{ color: var(--muted); font-size: .85rem; }}
  .nav {{ margin: .5rem 0 0; font-size: .95rem; }}
  .nav a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
  .nav a:hover {{ text-decoration: underline; }}
  .strip {{ display: flex; flex-wrap: wrap; gap: .75rem; margin: 1.25rem 0 .5rem; }}
  .stat {{ flex: 1 1 160px; background: var(--panel); border: 1px solid var(--line);
           border-radius: 8px; padding: .75rem .9rem; }}
  .stat-skill {{ font-weight: 700; font-size: 1rem; }}
  .stat-tier {{ color: var(--accent); font-size: 1.35rem; font-variant-numeric: tabular-nums; }}
  .stat-pts {{ color: var(--muted); font-size: .85rem; }}
  .muted-text {{ color: var(--muted); font-weight: 400; }}
  .total {{ flex: 1 1 160px; background: #14251c; border: 1px solid var(--on);
            border-radius: 8px; padding: .75rem .9rem; }}
  .total .stat-tier {{ color: var(--on); }}
  .card {{ background: var(--panel); border: 1px solid var(--line);
           border-radius: 10px; padding: 1.1rem 1.2rem; margin: 1.5rem 0; }}
  .scroll {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }}
  table {{ border-collapse: collapse; width: 100%; background: var(--panel); }}
  th, td {{ padding: .4rem .6rem; border-bottom: 1px solid var(--line);
            text-align: left; white-space: nowrap; }}
  thead th {{ background: #1d222c; font-size: .78rem; text-transform: uppercase;
              letter-spacing: .4px; color: var(--muted); }}
  tbody th {{ font-weight: 600; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .cbadges {{ text-align: center; }}
  .badge {{ display: inline-grid; place-items: center; width: 16px; height: 16px;
            border-radius: 3px; font-size: 10px; font-weight: 700; margin: 0 1px; }}
  .badge.on {{ background: var(--on); color: #06231a; }}
  .badge.off {{ background: var(--off); color: #6b7180; }}
  .alert {{ background: #2a1f10; border: 1px solid var(--warn); color: #f2dca6;
            border-radius: 8px; padding: .8rem 1rem; margin: 0 0 1.25rem;
            font-size: .9rem; }}
  /* --- Community-buff level toggle ------------------------------------- */
  .bufftoggle {{ display: flex; flex-wrap: wrap; align-items: center;
                 gap: .5rem .75rem; margin: 1.25rem 0 0; }}
  .bt-label {{ color: var(--muted); font-size: .85rem; font-weight: 600;
               text-transform: uppercase; letter-spacing: .4px; }}
  /* The two segments live in their own flex box so the corner rounding can key
     off :first-child / :last-child. Keying off :first-of-type instead would be
     silently wrong: the active segment is a <span> and the inactive one an <a>,
     so "of-type" counts them in separate sequences and both would claim the
     right-hand corner. */
  .bt-segs {{ display: inline-flex; }}
  .bt-seg {{ display: inline-flex; align-items: baseline; gap: .4rem;
             padding: .35rem .75rem; font-size: .9rem; font-weight: 600;
             border: 1px solid var(--line); background: var(--panel);
             color: var(--muted); text-decoration: none; }}
  .bt-segs > :first-child {{ border-radius: 6px 0 0 6px; }}
  .bt-segs > :last-child {{ border-radius: 0 6px 6px 0; border-left: 0; }}
  .bt-seg:hover {{ color: var(--text); }}
  .bt-seg.active {{ background: #1b2b3d; border-color: var(--accent);
                    color: var(--text); cursor: default; }}
  .bt-seg .bt-pts {{ color: var(--muted); font-weight: 400;
                     font-variant-numeric: tabular-nums; font-size: .82rem; }}
  .bt-seg.active .bt-pts {{ color: var(--accent); }}
  .bt-note {{ margin: .4rem 0 0; color: var(--muted); font-size: .82rem; }}
  tr.failed td {{ color: var(--warn); }}
  /* Considered and priced at nothing (the loot / XP shrines): greyed rather than
     omitted, so a reader can see the row was looked at. */
  tr.dim > th, tr.dim > td {{ color: var(--muted); font-style: italic; }}
  tbody tr:hover {{ background: #1b2029; }}
  /* --- Player search --------------------------------------------------- */
  .search {{ position: relative; max-width: 420px; margin: .25rem 0 1.25rem; }}
  .search input {{
    width: 100%; padding: .55rem .75rem; font: inherit;
    color: var(--text); background: var(--panel);
    border: 1px solid var(--line); border-radius: 8px;
  }}
  .search input:focus {{ outline: none; border-color: var(--accent); }}
  .search-results {{
    position: absolute; z-index: 5; left: 0; right: 0; margin-top: .3rem;
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 8px; overflow: hidden; box-shadow: 0 8px 24px rgba(0,0,0,.4);
  }}
  /* The result row holds two controls (pin, jump), so it is a flex CONTAINER and
     .sr-jump is the button that used to be .sr-item itself. */
  .sr-item {{
    display: flex; align-items: center; gap: .2rem; padding: 0 .7rem;
    border-bottom: 1px solid var(--line);
  }}
  .sr-jump {{
    display: flex; justify-content: space-between; align-items: center;
    gap: 1rem; flex: 1; padding: .45rem 0; font: inherit;
    text-align: left; color: var(--text); background: none; border: 0;
    cursor: pointer;
  }}
  .sr-item:last-child {{ border-bottom: 0; }}
  .sr-item:hover, .sr-jump:focus {{ background: #1b2029; outline: none; }}
  .sr-name {{ font-weight: 600; }}
  .sr-trial {{ color: var(--accent); font-size: .85rem; }}
  .sr-empty {{ padding: .45rem .7rem; color: var(--muted); }}
  /* --- Pinned members --------------------------------------------------- */
  .fav {{ background: none; border: 0; padding: 0 .3rem 0 0; margin: 0;
          font-size: 1rem; line-height: 1; color: var(--off); cursor: pointer; }}
  .fav:hover, .fav:focus {{ color: var(--warn); outline: none; }}
  .fav.on {{ color: var(--warn); }}
  .pinned {{ border-color: var(--accent); }}
  .pin-list {{ display: flex; flex-direction: column; }}
  .pin {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: .2rem .7rem;
          padding: .4rem 0; border-bottom: 1px solid var(--line); }}
  .pin:last-child {{ border-bottom: 0; }}
  .pin-name {{ font-weight: 700; }}
  .pin-trial {{ color: var(--accent); font-weight: 600; }}
  .pin-detail {{ color: var(--muted); font-size: .85rem; }}
  /* No colour of its own: the band class (.ok-text / .warn-text / .danger-text)
     paints it, so a pinned row reads the same red or green as the trial card. */
  .pin-margin {{ font-size: .85rem; }}
  .pin-stale .pin-trial {{ color: var(--muted); font-style: italic; font-weight: 400; }}
  .pin-jump {{ margin-left: auto; background: none; border: 1px solid var(--line);
               border-radius: 6px; color: var(--accent); font: inherit;
               font-size: .82rem; padding: .1rem .5rem; cursor: pointer; }}
  .pin-jump:hover {{ border-color: var(--accent); }}
  .pin-clear {{ background: none; border: 0; padding: 0; font: inherit;
                font-size: .85rem; color: var(--accent); cursor: pointer;
                text-decoration: underline; }}
  .pin-hint {{ margin: -.9rem 0 1.25rem; }}
  .bench-name {{ display: inline-flex; align-items: center; white-space: nowrap;
                 margin: 0 .8rem .3rem 0; }}
  /* --- Sortable headers ----------------------------------------------- */
  table.sortable th.sort {{ cursor: pointer; user-select: none; }}
  table.sortable th.sort:hover {{ color: var(--text); }}
  .arrow {{ display: inline-block; margin-left: .25rem; color: var(--off);
            font-size: .85em; }}
  .arrow.active {{ color: var(--accent); }}
  /* --- Row jump highlight --------------------------------------------- */
  @keyframes rowflash {{
    0% {{ background: var(--accent); }}
    100% {{ background: transparent; }}
  }}
  tr.row-flash > th, tr.row-flash > td {{ animation: rowflash 1.8s ease-out; }}
  section.card.row-flash {{ animation: rowflash 1.8s ease-out; }}
  /* --- Community-buff level selector ----------------------------------- */
  /* Laid out so the readout never reflows the slider as the digits change:
     the level number and the three magnitudes sit in a fixed-min-width span with
     tabular figures, which is what stops the control jittering under the thumb. */
  .bufflevel {{ margin: 1.25rem 0 0; }}
  .bl-row {{ display: flex; flex-wrap: wrap; align-items: center; gap: .5rem .9rem; }}
  .bl-label {{ color: var(--muted); font-size: .85rem; font-weight: 600;
               text-transform: uppercase; letter-spacing: .4px; }}
  .bl-range {{ flex: 0 1 18rem; accent-color: var(--accent); }}
  .bl-readout {{ display: inline-flex; flex-wrap: wrap; align-items: baseline;
                 gap: .1rem .6rem; font-size: .9rem;
                 font-variant-numeric: tabular-nums; min-width: 22rem; }}
  .bl-mag {{ color: var(--muted); font-size: .82rem; }}
  .bl-reset {{ background: none; border: 1px solid var(--line); border-radius: 6px;
               color: var(--muted); cursor: pointer; font: inherit;
               font-size: .8rem; padding: .2rem .55rem; }}
  .bl-reset:hover {{ color: var(--text); border-color: var(--accent); }}
  .bl-note {{ margin: .4rem 0 0; color: var(--muted); font-size: .82rem;
              max-width: 78ch; }}
  .bl-off {{ color: var(--warn); font-weight: 600; }}
  /* Off the published level, the whole strip is tinted: the summary numbers are
     the ones most likely to be quoted out of context, so they carry the reminder. */
  .strip.off-level {{ outline: 1px dashed var(--warn); outline-offset: .4rem; }}
  footer {{ margin-top: 2rem; color: var(--muted); font-size: .8rem; }}
  footer ol {{ padding-left: 1.2rem; }}
  footer li {{ margin: .25rem 0; }}
  code {{ background: #0b0d11; padding: 0 .3em; border-radius: 3px; }}
</style>
</head>
<body>
<header>
  <h1>Guild Trials &mdash; Week of {html.escape(week['week_date'])}
      <span class="meta">({html.escape(_assignment_label(week))})</span>{buff_h1}</h1>
  <p class="meta">{html.escape(site.title)} &middot; {week['member_count']} members &middot;
     {html.escape(_assignment_detail(week))} &middot;
     generated {html.escape(week['generated_at'])} (UTC)</p>
  <p class="nav"><a href="index.html">&larr; Skill Register</a>
     &nbsp;&middot;&nbsp; <a href="{site.sibling_home}">{html.escape(site.sibling_title)} &rarr;</a></p>
</header>
<main>
  {alert_html}{buff_toggle}{buff_slider}
  <!-- Filled in by the page script from localStorage and unhidden only when this
       reader has pinned somebody; it starts hidden so a first-time visitor sees no
       empty scaffolding. -->
  <section class="card pinned" id="pinned-section" hidden>
    <h2>Your members</h2>
    <p class="meta">Pinned on this device &middot;
       <button type="button" id="pin-clear" class="pin-clear">clear all</button></p>
    <div id="pinned-list" class="pin-list"></div>
  </section>
  <div class="strip" id="strip">{strip}</div>

  <div class="search">
    <input id="member-search" type="search" autocomplete="off"
           placeholder="Search a member&hellip; (jump to their trial &amp; row)"
           aria-label="Search for a guild member">
    <div id="search-results" class="search-results" role="listbox" hidden></div>
  </div>
  <p class="meta pin-hint">Tip: the <span class="fav on">&#9733;</span> beside any
     member pins their trial to the top of this page and remembers it on this
     device, so your own assignment is the first thing you see next week.</p>
  {cards}

  <section class="card" id="bench-section">
    <h2>Bench</h2>
    <p class="meta">{len(bench)} member(s) not assigned to a trial this week
       (beyond {len(week['skills'])} &times; {week['cap']}).</p>
    <p>{bench_html}</p>
  </section>
{min_levels_section}{upgrades_section}{shrines_section}</main>
<footer>
  <h3>Assumptions &amp; caveats</h3>
  <p>This page is a <strong>model</strong>, not live game data. Every number
     below rests on assumptions flagged for replacement once an empirical trial
     capture is harvested.</p>
  <ol>
    <li><strong>Tier curve &amp; work target (CONFIRMED).</strong> The
        difficulty level starts at 100 and rises +10 per tier
        (<code>DifficultyLevel(t) = 100 + 10*(t-1)</code>). The work a party must
        out-produce is
        <code>TotalWork = DifficultyLevel &times; 400 &times; (1 + Players/100)</code>
        &mdash; the confirmed formula, so no separate calibration scale is
        applied (TARGET_SCALE = {week['target_scale']:g}).</li>
    <li><strong>Success rate (CONFIRMED).</strong> Per action,
        <code>MAX(0.05, 0.8 &times; (1 + &Delta; &times; s + bonus))</code> where
        <code>&Delta; = SkillLevel + BuildingSkillLevels &minus; DifficultyLevel</code>,
        the slope <code>s</code> is <code>+0.005</code> at or above the difficulty
        and <code>&minus;0.01</code> below it, and success is floored at
        <code>0.05</code>. <em>BuildingSkillLevels</em> comes from the guild's
        buildings (see below). For Enhancing the <code>bonus</code>
        is the EnhancingSuccessRate (enhancer tool success; the Observatory's
        enhancing-success buff is 0 in the live data).</li>
    <li><strong>Points formula, and partial-tier credit (2026-08-11).</strong>
        A trial is now credited for progress into the tier it did <em>not</em>
        finish, at half rate: <code>0.5% credit per 1% progress</code>. So with
        <code>T</code> the tier banked and <code>f</code> the fraction of the next
        one completed when the hour ran out,
        <code>points = 100 + 100 &times; (T + {config.TRIAL_PARTIAL_CREDIT_RATE} &times; f)</code>.
        <br>
        <strong>The shape matters more than the formula.</strong> Each tier is now a
        <em>ramp</em> worth {_num(config.TRIAL_POINTS_PER_TIER * config.TRIAL_PARTIAL_CREDIT_RATE, 0)}
        points followed by a <em>step</em> worth
        {_num(config.TRIAL_POINTS_PER_TIER * (1 - config.TRIAL_PARTIAL_CREDIT_RATE), 0)}
        at the boundary &mdash; the old {config.TRIAL_POINTS_PER_TIER}-point cliff
        halved, not abolished. Every seat and every swap now moves the score, where
        before a member who crossed no threshold was worth exactly nothing; that is
        why the tables below show fractional points, and why a marginal seat now has
        a price. The residual step is why reaching for one more tier is still worth
        doing even when it can only be held by seconds &mdash; see
        <em>what the deterministic score does not say</em> below.
        <br>
        The <code>100 + 100*T</code> base schedule remains an ASSUMPTION fitted to
        the only observed data (milking tier1&rarr;200, tier2&rarr;300); whether the
        flat 100 is also earned by a party that completes <em>no</em> tier is
        unconfirmed, and is withheld here.</li>
    <li><strong>Alchemy = the &ldquo;Bell Farming&rdquo; column.</strong> The
        guild named a sheet column &ldquo;Bell Farming&rdquo; as a joke &mdash;
        it actually records each member's <em>Alchemy</em> level. So Alchemy
        levels and Tool/Top/Bot ownership are read straight from that column,
        exactly like any other skill (no proxy, no stand-in).</li>
    <li><strong>Equipment baselines.</strong> Everyone is assumed to run a
        <code>+7</code> tool (celestial if the sheet's tool box is checked, else
        holy), a <code>+3</code> correct-group cape, and a <code>+7</code> family
        piece; <code>+7</code> top/bottom count only when checked. Enhancing is
        special: its tool grants success (not speed) and its gloves grant speed
        (not efficiency). Skilling top/bottom are modelled as efficiency for all
        skills (in-game the Enhancer's set grants speed instead).</li>
    <li><strong>Community buffs (magnitudes CONFIRMED; level assumed).</strong>
        Three community buffs are modelled, one per skill family, and each is
        bought with cowbells on its own <strong>level ladder 1&ndash;20</strong>.
        The magnitude follows the game's usual rule
        <code>flatBoost + (level&minus;1) &times; flatBoostLevelBonus</code>, but
        note that here <code>flatBoost &ne; flatBoostLevelBonus</code>: a community
        buff opens at a large base and then creeps, so the
        <code>per_level &times; level</code> shortcut the buildings and shrines
        follow does <em>not</em> apply. From the client data:
        <em>Gathering</em> (Milking / Foraging / Woodcutting)
        <code>0.20 + 0.005/level</code>; <em>Enhancing</em> speed
        <code>0.20 + 0.005/level</code>; <em>Production</em> efficiency (incl.
        Alchemy) <code>0.14 + 0.003/level</code>. This page is built at
        <strong>level {buff_level}</strong> &mdash;
        {_pct(week.get('community_buff_gathering'))} /
        {_pct(week.get('community_buff_enhancing'))} /
        {_pct(week.get('community_buff_production'))} respectively{switch_phrase}.
        The guild's <em>real</em> buff levels are in no capture this repo
        holds, which is why level&nbsp;1 is the published default: the same gap the
        shrine levels carry. The two remaining community buffs (Experience &rarr;
        wisdom, Combat Drop Quantity) are deliberately unmodelled &mdash; XP and
        loot are not in the race's loop.
        <br>
        <strong>One WORKING ASSUMPTION remains, and it is the expensive one.</strong>
        The gathering buff is applied as a lab-style double-progress chance,
        scaling each member's rate by <code>(1 + doubleChance)</code> &mdash;
        {_pct(week.get('community_buff_gathering'))} of buff plus a placeholder ~5%
        carried on gear, pending the per-member gear harvest. But the game types
        that buff as <em>gathering quantity</em>, which is a different thing from
        the <em>double progress</em> the engine's <code>doubleProgressChance</code>
        field reports. If the two do not in fact coincide, the doubling chance falls
        to the ~5% gear term alone and every gathering rate here is some 19% too
        high. The settling measurement is a single progress capture from a gathering
        trial while the buff is live.</li>
    <li><strong>Houses (per-member, from the sheet).</strong> Each member's
        per-skill house level is read from the guild sheet's &ldquo;H&rdquo;
        column. Per the game data, gathering and production house rooms grant
        <code>+0.015</code> efficiency per level, while the enhancing house
        (Observatory) grants <code>+0.010</code> action-speed per level rather
        than efficiency. A blank H cell falls back to the assumed default of
        <code>level&nbsp;4</code>; levels are clamped to the in-game max of 8.</li>
    <li><strong>Guild buildings (guild-wide, CONFIRMED game data).</strong>
        Quite separate from the personal houses above: each of the ten skilling
        <em>guild</em> buildings grants <code>+2 levels</code> in its own skill to
        <em>every</em> member of the guild, per building level &mdash; Guild
        Brewery&rarr;Brewing, Guild Laboratory&rarr;Alchemy, Guild
        Observatory&rarr;Enhancing and so on &mdash; up to <code>+40</code> at the
        building cap of level&nbsp;20. Those levels are added to each member's own
        level in the success calc above (the <em>BuildingSkillLevels</em> term)
        but deliberately <em>not</em> to work power, which no capture has yet
        confirmed. Building levels are entered by hand in
        <code>config.GUILD_BUILDING_LEVELS</code> for now, not read from the
        sheet: {_guild_buildings_footnote(week)}. The
        <a href="#upgrades-section">upgrade section</a> above works out how many
        levels of each drawn building would buy another tier, what that costs in
        total, and how many weeks the spend takes to earn itself back.</li>
    <li><strong>{html.escape(_assignment_footnote(week))}</strong></li>
  </ol>
  <p>Machine-readable copy of this page's data: <code>{json_name}</code>.
     Static build from the public guild sheet; no credentials, read-only.</p>
</footer>
<script id="assign-data" type="application/json"
        data-pin-key="guild-trials.pins.{site.key}">{assign_json}</script>
{levels_script}
<script>{_TRIALS_JS}</script>
</body>
</html>
"""


# Player search for the sign-up page. The same behaviour as the full-optimum
# page's search, minus the sortable-table machinery (these rosters are ordered by
# volunteer-then-fill, which is meaningful, so they are deliberately not sortable).
# Plain string with single braces so it drops verbatim into the f-string template;
# it depends only on the embedded #signup-data JSON.
_SIGNUP_JS = r"""
(function () {
  "use strict";
  var dataEl = document.getElementById("signup-data");
  var data = dataEl ? JSON.parse(dataEl.textContent) : [];
  var input = document.getElementById("member-search");
  var panel = document.getElementById("search-results");
  if (!input || !panel) return;

  function jump(rowId) {
    var el = document.getElementById(rowId);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.remove("row-flash");
    void el.offsetWidth; // force reflow so the flash animation restarts
    el.classList.add("row-flash");
  }

  function clearPanel() {
    panel.hidden = true;
    while (panel.firstChild) panel.removeChild(panel.firstChild);
  }

  function renderResults(q) {
    q = q.trim().toLowerCase();
    while (panel.firstChild) panel.removeChild(panel.firstChild);
    if (!q) { panel.hidden = true; return; }
    var hits = data.filter(function (d) {
      return d.n.toLowerCase().indexOf(q) !== -1;
    }).slice(0, 12);
    panel.hidden = false;
    if (!hits.length) {
      var empty = document.createElement("div");
      empty.className = "sr-empty";
      empty.textContent = "No member matches that name.";
      panel.appendChild(empty);
      return;
    }
    hits.forEach(function (h) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "sr-item";
      var name = document.createElement("span");
      name.className = "sr-name";
      name.textContent = h.n;
      var trial = document.createElement("span");
      trial.className = "sr-trial";
      trial.textContent = h.t;
      b.appendChild(name);
      b.appendChild(trial);
      b.addEventListener("click", function () {
        jump(h.r);
        input.value = h.n;
        clearPanel();
      });
      panel.appendChild(b);
    });
  }

  input.addEventListener("input", function () { renderResults(input.value); });
  input.addEventListener("focus", function () {
    if (input.value.trim()) renderResults(input.value);
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { clearPanel(); }
  });
  document.addEventListener("click", function (e) {
    if (e.target !== input && !panel.contains(e.target)) clearPanel();
  });
})();
"""


def _slack_band(slack: Optional[float]) -> str:
    """CSS class banding a time margin: red / amber / green.

    Thresholds are ``config.SLACK_THIN`` and ``config.SLACK_OK`` — see the note
    there for why they sit where they do. ``None`` (no tier banked) is red: a trial
    that scored nothing has no margin at all, and must never render as safe.
    """
    if slack is None:
        return "danger-text"
    if slack < config.SLACK_THIN:
        return "danger-text"
    if slack < config.SLACK_OK:
        return "warn-text"
    return "ok-text"


def _pct(fraction: Optional[float]) -> str:
    """A margin fraction as a one-decimal percentage ('16.4%'); '—' for None."""
    if fraction is None:
        return "&mdash;"
    return f"{fraction * 100:.1f}%"


def _prob(p: Optional[float]) -> str:
    """A clear probability as a percentage. Never rounds a real risk away.

    99.9% and 100% are different claims, and the second one is never true, so a
    probability that is merely very high is clamped to "> 99.9%" rather than
    displayed as certainty.
    """
    if p is None:
        return "&mdash;"
    if p >= 0.9995:
        return "&gt; 99.9%"
    if p >= 0.995:
        return f"{p * 100:.1f}%"
    return f"{p * 100:.0f}%"


# The odds at which a lineup stops being a problem. Shared by _prob_band's green
# threshold and the safety list's "this is where the moves stop mattering" note, so
# the page cannot call a trial comfortable in one place and worth fixing in another.
_PROB_COMFORTABLE = 0.99


def _prob_band(p: Optional[float]) -> str:
    """CSS class banding a clear probability: red / amber / green.

    Deliberately banded on the PROBABILITY rather than on the margin, because the
    margin-to-probability map is violently non-linear near the buzzer: with the
    measured sigma the whole decision-relevant range of margins is 0-6%, so the
    existing SLACK_THIN / SLACK_OK thresholds paint a 99%-certain lineup red.
    Thresholds here are the ones an officer would actually name.
    """
    if p is None:
        return "danger-text"
    if p < 0.90:
        return "danger-text"
    if p < _PROB_COMFORTABLE:
        return "warn-text"
    return "ok-text"


def _risk_phrase(trial: dict) -> str:
    """The trial's odds, as a coloured phrase. Empty when not computed."""
    p = trial.get("clear_probability")
    if p is None:
        return ""
    return (
        f' &middot; holds <span class="{_prob_band(p)}">{_prob(p)}</span> '
        "of the time"
    )


def _margin_phrase(trial: dict, budget: float) -> str:
    """How narrowly this trial banked its score, as a coloured phrase.

    Points are a STEP function of the tier, so the score cannot show whether a tier
    was held with ten minutes to spare or nine seconds. This spells it out: the
    clock reading when the last completed tier finished, and what was left of the
    per-trial budget at that moment.
    """
    tier = trial.get("tier_reached") or 0
    secs = trial.get("clear_seconds")
    if tier < 1 or secs is None:
        return '<span class="danger-text">no tier banked</span>'
    # Same fact, two forms; derive the fraction if only the seconds are present so
    # the phrase and its colour band can never disagree.
    slack = trial.get("slack_fraction")
    if slack is None:
        slack = 1.0 - secs / budget
    return (
        f'<span class="{_slack_band(slack)}">tier {tier} banked at '
        f'{_num(secs, 0)}s of {_num(budget, 0)}s &middot; {_num(budget - secs, 0)}s '
        f'spare ({_pct(slack)})</span>'
    )


def _render_safety_section(p: dict, thinnest: Optional[dict], riskiest: Optional[dict]) -> str:
    """The advisory points-preserving moves that make the weakest trial likelier to hold.

    The counterpart to the points swaps card: same structure, different currency.
    Every row leaves the score untouched (guaranteed by ``signup._safety_swaps``) and
    strictly lifts the thinnest trial, so the columns read as a ladder — each move's
    ``after`` is the next move's ``before``.

    REPORTED IN ODDS, SELECTED ON MARGIN. The search ranks candidates on the time
    margin, where its guarantee lives (points exactly preserved, thinnest strictly
    raised); this only translates the result into the unit an officer decides in.
    The margin is kept beside it as the supporting detail rather than dropped,
    because it is the quantity the move actually acts on — and because a reader who
    sees only "83% -> 97%" cannot tell whether that came from twelve seconds or two
    minutes.
    """
    moves = p.get("safety_swaps") or []
    before = p.get("min_slack_fraction")
    after = p.get("safety_min_slack")
    prob_before = riskiest.get("clear_probability") if riskiest else None
    prob_after = p.get("safety_min_probability")
    target = config.SIGNUP_SAFETY_TARGET

    if before is None:
        return ""  # nothing banks a tier: margin is not this page's problem yet

    if not moves:
        if before >= target:
            weakest = f" ({html.escape(riskiest['skill'])})" if riskiest else ""
            body = (
                f'<p class="meta">None needed &mdash; every banking trial already holds '
                f'with at least {_pct(target)} of the hour spare. Least likely: '
                f'<span class="{_prob_band(prob_before)}">{_prob(prob_before)}</span>'
                f'{weakest}, thinnest margin {_pct(before)}.</p>'
            )
        else:
            thin_name = html.escape(thinnest["skill"]) if thinnest else "the thinnest trial"
            # Only claim the override option was tried if it actually was.
            reach = (
                "not even one that overrides a sign-up"
                if config.SIGNUP_SAFETY_ALLOW_OVERRIDES
                else "and moves that override a sign-up are switched off"
            )
            body = (
                f'<p class="meta">None found &mdash; no move that preserves the score '
                f'widens {thin_name}\'s <span class="{_slack_band(before)}">'
                f'{_pct(before)}</span> margin, {reach}. That leaves the weakest trial '
                f'holding <span class="{_prob_band(prob_before)}">{_prob(prob_before)}'
                f'</span> of the time. '
                f'Every remaining option would cost points. Improving it needs a '
                f'stronger party for that trial than this roster can field, so the '
                f'realistic choices are to accept the risk or to trade points for it '
                f'deliberately.</p>'
            )
        return f"""
  <section class="card">
    <h2>Safety swaps &mdash; same points, better odds</h2>
    {body}
  </section>"""

    capped = len(moves) >= config.SIGNUP_SAFETY_MAX_MOVES
    # The tail leads on ODDS, because that is the question ("is this lineup safe?").
    # The margin target only gets a mention when the odds are NOT yet comfortable —
    # otherwise the page would announce a lineup as "still short" while reporting it
    # as better than 99.9% certain, which is how a reader learns to distrust a page.
    if prob_after is not None and prob_after >= _PROB_COMFORTABLE:
        tail = "&mdash; comfortable."
    elif after is not None and after >= target:
        tail = f"&mdash; at the {_pct(target)} margin the pass aims for."
    elif capped:
        tail = (
            f"&mdash; still short, and the list stops at its "
            f"{config.SIGNUP_SAFETY_MAX_MOVES}-move limit. Apply these and rebuild to "
            f"see what comes next."
        )
    else:
        tail = "&mdash; still short; no further points-preserving move helps."
    # WHERE THE LIST STOPS EARNING ITS KEEP. The search stops on a MARGIN target
    # (config.SIGNUP_SAFETY_TARGET), and with the measured sigma that target sits far
    # past the point of diminishing returns: on the live SC lineup one move takes the
    # weakest trial from 78.5% to 99.6% and the remaining seven move it from 100% to
    # 100%. Rather than silently hand an officer eight moves of which one matters, say
    # which prefix does the work. Presentational only — the search is untouched, and
    # every move remains listed for anyone who wants the last fraction of a percent.
    enough = None
    for i, m in enumerate(moves, start=1):
        after_p = m.get("min_prob_after")
        if after_p is not None and after_p >= _PROB_COMFORTABLE:
            enough = i
            break
    gold_plating = ""
    if enough is not None and enough < len(moves):
        spare = len(moves) - enough
        first = "first move alone takes" if enough == 1 else f"first {enough} take"
        gold_plating = (
            f' <strong>The {first} the weakest trial past '
            f'{_prob(_PROB_COMFORTABLE)}</strong>, so the remaining {spare} are '
            f'refinement rather than repair &mdash; the list runs on because the pass '
            f'stops on a {_pct(target)} margin, which at this party\'s spread is well '
            f'past the point where extra room changes the odds.'
        )

    lead = (
        f'These {len(moves)} move(s) take the weakest trial from '
        f'<span class="{_prob_band(prob_before)}">{_prob(prob_before)}</span> to '
        f'<span class="{_prob_band(prob_after)}">{_prob(prob_after)}</span> likely to '
        f'hold, widening the thinnest margin from '
        f'<span class="{_slack_band(before)}">{_pct(before)}</span> to '
        f'<span class="{_slack_band(after)}">{_pct(after)}</span> {tail} '
        f'The score does not change &mdash; it stays {_cp(p["enforced_total"])} points, by '
        f'construction rather than by luck &mdash; so this list is about surviving an '
        f'optimistic constant or a missing piece of gear, not about scoring more. Each '
        f'is advisory, and they are cumulative: apply them in order.{gold_plating}'
    )

    n_override = sum(1 for m in moves if m.get("overrides_signup"))
    rows = []
    for m in moves:
        # Per-trial effect: odds first, with the margin that produced them in
        # parentheses. A trial can appear here having got SAFER or WORSE — a move
        # that lifts the weakest trial often costs a comfortable one a little, which
        # is exactly the trade the reader is being asked to approve.
        changes = "".join(
            f'<li>{html.escape(c["skill"])}: '
            f'<span class="{_prob_band(c.get("prob_before"))}">'
            f'{_prob(c.get("prob_before"))}</span> &rarr; '
            f'<span class="{_prob_band(c.get("prob_after"))}">'
            f'{_prob(c.get("prob_after"))}</span> '
            f'<span class="meta">({_pct(c["before"])} &rarr; {_pct(c["after"])} '
            f'margin)</span></li>'
            for c in m.get("trial_changes") or []
        )
        detail = html.escape(m["note"])
        if changes:
            detail += f'<ul class="swap-moves">{changes}</ul>'
        chips = f'<span class="chip safety">{html.escape(m["action"])}</span>'
        if m.get("overrides_signup"):
            chips += '<span class="chip override" title="Moves a member out of the trial they ticked">overrides sign-up</span>'
        rows.append(
            f'<tr><td>{chips}</td><td>{detail}</td>'
            f'<td class=num><span class="{_prob_band(m.get("min_prob_before"))}">'
            f'{_prob(m.get("min_prob_before"))}</span> &rarr; '
            f'<span class="{_prob_band(m.get("min_prob_after"))}">'
            f'{_prob(m.get("min_prob_after"))}</span></td>'
            f'<td class=num><span class="{_slack_band(m["min_before"])}">'
            f'{_pct(m["min_before"])}</span> &rarr; '
            f'<span class="{_slack_band(m["min_after"])}">{_pct(m["min_after"])}</span>'
            f'</td></tr>'
        )

    override_note = ""
    if n_override:
        override_note = (
            f'<p class="meta">{n_override} of these move a member out of the trial they '
            f'ticked (flagged <span class="chip override">overrides sign-up</span>). '
            f'The search only resorts to that once the uncommitted members alone cannot '
            f'lift the thinnest trial &mdash; which happens when that trial\'s party is '
            f'entirely volunteers, as it is here. The points swaps above already '
            f'override sign-ups when points justify it; these ask the same of you for '
            f'margin instead, so they are a judgement call, not an instruction.</p>'
        )

    return f"""
  <section class="card">
    <h2>Safety swaps &mdash; same points, better odds</h2>
    <p class="meta">{lead}</p>
    <div class="scroll">
      <table>
        <thead><tr><th>Move</th><th>Detail</th>
          <th class=num>Weakest trial holds</th>
          <th class=num>Thinnest margin</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>{override_note}
  </section>"""


def _render_signup_html(p: dict, site: "GuildSite") -> str:
    """Render the sign-up optimiser page from a ``signup.SignupPlan`` dict.

    The enforced plan (real sign-ups locked, open seats filled from the
    uncommitted pool) is shown per trial with volunteers colour-coded green and
    recommended fills blue; below it, the minimal strictly-improving swaps to
    reach the full-roster optimum, and the optimum itself for comparison.

    Each trial also reports the time margin by which it banked its score, and the
    summary strip leads with the THINNEST of them, because the enforced plan is the
    one assignment on this site that the optimizer's safety pass never touches: the
    volunteers are locked, so whatever margin the real sign-ups leave is what ships.
    """
    optimal_by_skill = {o["skill"]: o for o in p["optimal_summary"]}
    budget = p.get("budget_seconds") or config.TRIAL_TIME_BUDGET_SECONDS

    # --- Safety tile: the thinnest margin in the shipped lineup -------------
    # The weakest link, since a lost tier costs its points outright. Excludes
    # trials that banked no tier (they have no margin); those show separately on
    # their own card as "no tier banked".
    thinnest = min(
        (t for t in p["trials"] if (t.get("tier_reached") or 0) >= 1),
        key=lambda t: t.get("slack_fraction") or 0.0,
        default=None,
    )
    if thinnest is None:
        safety_tile = """
    <div class="stat"><div class=stat-skill>Thinnest margin</div>
      <div class="stat-tier danger-text">&mdash;</div>
      <div class=stat-pts>no trial banks a tier</div></div>"""
    else:
        thin_slack = thinnest.get("slack_fraction")
        # Where the safety swaps below would take that margin — the tile is the first
        # thing read, so it should say both what ships and what is available.
        recoverable = p.get("safety_min_slack")
        recover = ""
        if recoverable is not None and thin_slack is not None and recoverable > thin_slack:
            recover = (
                f' &middot; <span class="{_slack_band(recoverable)}">{_pct(recoverable)}'
                f'</span> with the safety swaps'
            )
        safety_tile = f"""
    <div class="stat"><div class=stat-skill>Thinnest margin</div>
      <div class="stat-tier {_slack_band(thin_slack)}">{_pct(thin_slack)}</div>
      <div class=stat-pts>{html.escape(thinnest['skill'])} &middot;
        {_num(budget - (thinnest.get('clear_seconds') or 0.0), 0)}s spare of
        {_num(budget, 0)}s{recover}</div></div>"""

    # --- Odds tile: the same weak link, expressed as a probability -----------
    # Deliberately its OWN tile rather than a footnote on the margin. The two are
    # not interchangeable: the map from margin to probability is non-linear, and
    # the least likely trial to hold is not always the one with the thinnest
    # margin once party composition differs.
    riskiest = min(
        (t for t in p["trials"] if t.get("clear_probability") is not None),
        key=lambda t: t["clear_probability"],
        default=None,
    )
    if riskiest is None:
        odds_tile = """
    <div class="stat"><div class=stat-skill>Least likely to hold</div>
      <div class="stat-tier danger-text">&mdash;</div>
      <div class=stat-pts>no trial banks a tier</div></div>"""
    else:
        rp = riskiest["clear_probability"]
        # Where the safety swaps would take it. Same contract as the margin tile:
        # say both what ships and what is available, so the reader does not have to
        # scroll to find out whether the risk is fixable.
        rec_p = p.get("safety_min_probability")
        recover_p = ""
        if rec_p is not None and rec_p > rp + 1e-9:
            recover_p = (
                f' &middot; <span class="{_prob_band(rec_p)}">{_prob(rec_p)}</span>'
                f' with the safety swaps'
            )
        odds_tile = f"""
    <div class="stat"><div class=stat-skill>Least likely to hold</div>
      <div class="stat-tier {_prob_band(rp)}">{_prob(rp)}</div>
      <div class=stat-pts>{html.escape(riskiest['skill'])} tier
        {riskiest.get('tier_reached')} &middot; if the party turns up{recover_p}</div></div>"""

    # --- Summary strip: likely / with-swaps / ceiling / safety --------------
    # The three score tiles lead with THE OBJECTIVE, because that is the currency every
    # comparison on this page is made in (the swap gains, the gap, the ceiling all come
    # from the scorer) and the one the plan was actually chosen on. The rule has not
    # changed; the number it selects has — since 2026-08-14 the objective is E[credit
    # points] (config.OPT_OBJECTIVE), so these tiles are expected points and the
    # deterministic total is the secondary figure rather than the headline. The step
    # total — the confirmed award for the tiers the guild will see banked in game —
    # rides underneath, read defensively so a signup.json from before the patch still
    # renders.
    enforced_step = p.get("enforced_step_total")
    optimal_step = p.get("optimal_step_total")
    # Note the ARGUMENTS ARE THE OTHER WAY ROUND from the trials page's use of this
    # helper, and deliberately: there the headline is deterministic and the expectation
    # is the aside, here the headline IS the expectation and the deterministic score is
    # the aside. Same suppression rule (silent when the two agree within half a point),
    # opposite roles.
    signup_expected_note = _deterministic_total_note(
        p.get("enforced_total"), p.get("enforced_credit_total")
    )
    strip = f"""
    <div class="stat"><div class=stat-skill>Likely score</div>
      <div class=stat-tier>{_cp(p['enforced_total'])}</div>
      <div class=stat-pts>expected &middot; sign-ups + recommended fills &middot;
        {_gp(enforced_step)} pts from banked tiers{signup_expected_note}</div></div>
    <div class="stat"><div class=stat-skill>With swaps</div>
      <div class=stat-tier>{_cp(p['reachable_total'])}</div>
      <div class=stat-pts>after the swaps below</div></div>
    <div class="total"><div class=stat-skill>Optimal ceiling</div>
      <div class=stat-tier>{_cp(p['optimal_total'])}</div>
      <div class=stat-pts>best possible &middot; gap {_cp(p['gap'])} &middot;
        {_gp(optimal_step)} pts banked{_deterministic_total_note(
            p.get('optimal_total'), p.get('optimal_credit_total'))}</div></div>"""\
        f"""{safety_tile}{odds_tile}"""

    # --- Per-trial enforced rosters ----------------------------------------
    # Every row carries a stable DOM id so the player search can jump to it, the
    # same contract the full-optimum page uses (see _render_trial_card).
    def _row(r: dict, row_id: str) -> str:
        assigned = r["status"] == "assigned"
        cls = "assigned" if assigned else "rec"
        badges = _badge(r["tool"], "Tool") + _badge(r["top"], "Top") + _badge(r["bot"], "Bot")
        # A FILL NOW HAS A PRICE, AND IT MAY BE NEGATIVE. Under the old step objective a
        # marginal seat was worth exactly zero, so every rider was "safe". Partial credit
        # prices the seat — an extra head raises every tier's target — so a rider seated
        # under config.TRIAL_FILL_MAX_POINT_COST costs the party points, and the chip
        # prints the bill rather than implying the seat was free. "Fill (safe)" is now
        # reserved for a genuine zero (or a plan written before the patch, which carries
        # no gain at all).
        gain = r.get("fill_gain")
        if assigned:
            chip = '<span class="chip assigned">Signed up</span>'
        elif gain is not None and gain > 0:
            chip = f'<span class="chip rec">Fill +{_cp(gain)}</span>'
        elif gain is not None and gain < 0:
            chip = (
                f'<span class="chip cost" title="Seated at a stated cost in the '
                f'objective (config.TRIAL_FILL_MAX_POINT_COST)">Fill &minus;'
                f'{_cp(-gain)}</span>'
            )
        else:
            chip = '<span class="chip filler">Fill (safe)</span>'
        level = "" if r["level"] is None else r["level"]
        return (
            f'<tr class="{cls}" id="{row_id}">'
            f'<th scope=row>{html.escape(r["name"])}</th>'
            f'<td class=num>{level}</td>'
            f'<td class=cbadges>{badges}</td>'
            f'<td class=num>{_num(r["rate_final"])}</td>'
            f'<td>{chip}</td>'
            "</tr>"
        )

    cards = []
    # Search index: member -> (trial label, row id). Built alongside the cards so
    # a row can never appear in the index without existing in the DOM.
    signup_index: list[dict] = []
    for t_index, t in enumerate(p["trials"]):
        opt = optimal_by_skill.get(t["skill"], {})
        opt_tier = opt.get("tier_reached")
        opt_note = ""
        if opt_tier is not None and opt_tier != t["tier_reached"]:
            opt_note = (
                f' &middot; <span class="hl">optimal reaches tier {opt_tier} '
                f'({_cp(_credit_points(opt))} pts)</span>'
            )
        # How safe this lineup is, and how safe the optimum manages to be on the
        # same trial — the comparison is the point: a much wider margin next door
        # means the risk is ours, not the trial's.
        opt_slack = opt.get("slack_fraction")
        opt_margin = (
            f' &middot; optimal holds it with {_pct(opt_slack)} spare'
            if opt_slack is not None and (t.get("tier_reached") or 0) >= 1
            else ""
        )
        n_assigned = sum(1 for r in t["roster"] if r["status"] == "assigned")
        n_rec = sum(1 for r in t["roster"] if r["status"] == "recommended")
        # The trial's minimum sign-up level, where the officers set one. Stated on the
        # card because it explains an absence the reader would otherwise read as a bug:
        # a volunteer whose level the minimum forbids is not in this party (the game
        # would refuse the sign-up) — see the #ineligible-signups card.
        min_level = t.get("min_level")
        min_note = (
            f" &middot; minimum sign-up level <strong>{min_level}</strong>"
            if min_level is not None
            else ""
        )
        rows = "".join(
            _row(r, f"sr-{t_index}-{i}") for i, r in enumerate(t["roster"])
        )
        signup_index.extend(
            {
                "n": r["name"],
                "t": f"{t['skill']}"
                     f"{' (signed up)' if r['status'] == 'assigned' else ' (fill)'}",
                "r": f"sr-{t_index}-{i}",
            }
            for i, r in enumerate(t["roster"])
        )
        cards.append(f"""
  <section class="card">
    <h2>{html.escape(t['skill'])}</h2>
    <p class="meta">Party {t['party_size']} &middot; {_tier_phrase(t)}
       &middot; {_points_phrase(t)}{_expected_phrase(t)}
       &middot; {n_assigned} signed up, {n_rec} recommended,
       {t['open_seats']} seat(s) still open{min_note}{opt_note}</p>
    <p class="meta">Safety: {_margin_phrase(t, budget)}{_risk_phrase(t)}{opt_margin}</p>
    <div class="scroll">
      <table>
        <thead><tr><th>Member</th><th class=num>Level</th>
          <th>Tool / Top / Bot</th><th class=num>Rate @final</th><th>Status</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </section>""")
    cards_html = "".join(cards)

    # --- Swaps to reach optimal --------------------------------------------
    def _swap_detail(s: dict) -> str:
        """Detail cell: the note, plus the component moves for a reshuffle."""
        detail = html.escape(s["note"])
        if s.get("moves"):
            items = "".join(
                f'<li>in <strong>{html.escape(m["in"])}</strong>, '
                f'out {html.escape(m["out"])} '
                f'<span class="meta">(from {html.escape(m["from_skill"])})</span></li>'
                for m in s["moves"]
            )
            detail += f'<ul class="swap-moves">{items}</ul>'
        return detail

    # A points-equal plan is NOT necessarily a safe one, and the swap list only
    # knows about points. Where the thinnest trial is below the comfortable band,
    # say so here too — otherwise "already matches the optimal ceiling. Nothing to
    # change." reads as all-clear while a tier hangs on seconds. Live example
    # (SC, 2026-07-31): 4900 points, equal to the ceiling, with Foraging holding
    # tier 12 by 65 seconds against the optimum's 18%.
    safety_caveat = ""
    if thinnest is not None and (thinnest.get("slack_fraction") or 0.0) < config.SLACK_OK:
        thin_opt = optimal_by_skill.get(thinnest["skill"], {}).get("slack_fraction")
        versus = (
            f", against {_pct(thin_opt)} for the unconstrained optimum"
            if thin_opt is not None else ""
        )
        safety_caveat = f"""
    <p class="meta">Matching the ceiling on <em>points</em> is not the same as being
       safe. <span class="{_slack_band(thinnest.get('slack_fraction'))}">
       {html.escape(thinnest['skill'])} banks tier {thinnest['tier_reached']} with only
       {_pct(thinnest.get('slack_fraction'))} of the hour spare</span>{versus} &mdash; so
       an absence, a lapsed buff, or a slightly optimistic constant costs that whole
       tier. The optimizer's safety pass cannot help here: the volunteers are locked,
       so widening that margin is a human decision &mdash; see
       <em>Safety swaps</em> below.</p>"""

    if p["swaps"]:
        swap_rows = "".join(
            f'<tr><td><span class="chip {html.escape(s["action"])}">'
            f'{html.escape(s["action"])}</span></td>'
            f'<td>{_swap_detail(s)}</td>'
            f'<td class=num>+{_cp(s["gain"])}</td></tr>'
            for s in p["swaps"]
        )
        gained = sum(s["gain"] for s in p["swaps"])
        # Compared with a tolerance, not exactly. The totals are continuous since
        # partial-tier credit, so two lineups that are for all practical purposes level
        # can differ in the second decimal — and reporting "a further 1.5 points to the
        # ceiling" as a shortfall is noise dressed as advice. Half a point is well
        # inside the model's own error and far below one tier.
        if p["reachable_total"] >= p["optimal_total"] - 0.5:
            swap_lead = (
                f"These {len(p['swaps'])} move(s) raise the likely "
                f"{_cp(p['enforced_total'])} to {_cp(p['reachable_total'])} points "
                "&mdash; the optimal ceiling. Each is purely advisory and "
                "overrides a sign-up; a &ldquo;reshuffle&rdquo; is a small group "
                "of swaps that together lift one trial a tier."
            )
        else:
            swap_lead = (
                f"These {len(p['swaps'])} move(s) raise the likely "
                f"{_cp(p['enforced_total'])} to {_cp(p['reachable_total'])} points "
                f"(+{_cp(gained)}); a further "
                f"{_cp(p['optimal_total'] - p['reachable_total'])} "
                "to the optimal ceiling is not reachable without a wider reshuffle "
                "(see the comparison below). Each is advisory and overrides a "
                "sign-up."
            )
        swaps_section = f"""
  <section class="card">
    <h2>Recommended swaps to reach optimal</h2>
    <p class="meta">{swap_lead}</p>
    <div class="scroll">
      <table>
        <thead><tr><th>Move</th><th>Detail</th><th class=num>Gain</th></tr></thead>
        <tbody>{swap_rows}</tbody>
      </table>
    </div>{safety_caveat}
  </section>"""
    elif p["enforced_total"] >= p["optimal_total"]:
        swaps_section = f"""
  <section class="card">
    <h2>Recommended swaps to reach optimal</h2>
    <p class="meta">None &mdash; the enforced sign-up plan ({_cp(p['enforced_total'])} pts,
       {_gp(enforced_step)} from banked tiers) already matches the optimal ceiling
       ({_cp(p['optimal_total'])} pts, {_gp(optimal_step)} banked), so there is
       nothing to gain in <em>points</em>.</p>{safety_caveat}
  </section>"""
    else:
        swaps_section = f"""
  <section class="card">
    <h2>Recommended swaps to reach optimal</h2>
    <p class="meta">None found &mdash; the enforced sign-up plan ({_cp(p['enforced_total'])} pts,
       {_gp(enforced_step)} from banked tiers)
       sits {_cp(p['optimal_total'] - p['enforced_total'])} below the optimal ceiling
       ({_cp(p['optimal_total'])} pts, {_gp(optimal_step)} banked), but no swap (single or grouped) closes the gap
       without lowering another trial. Reaching the ceiling would need a wider
       reshuffle &mdash; compare the two rosters below.</p>{safety_caveat}
  </section>"""

    safety_section = _render_safety_section(p, thinnest, riskiest)

    # --- Optimal comparison table ------------------------------------------
    # Carries the optimum's own margin, which is what the optimizer's safety pass
    # maximised — the standard to read the enforced plan's margins against.
    # Both currencies again, side by side: Points is the step award for the banked tier,
    # Credit adds the part-finished one and is what the optimizer maximised — so a row
    # can tie the enforced plan on Points and still be visibly ahead on Credit. The tier
    # cell carries the partial progress that explains the difference.
    opt_rows = "".join(
        f'<tr><th scope=row>{html.escape(o["skill"])}</th>'
        f'<td class=num>{o["party_size"]}</td>'
        f'<td class=num>{o["tier_reached"]}'
        + (
            f'<span class="meta"> +{_pct(o.get("partial_fraction"))}</span>'
            if (o.get("partial_fraction") or 0.0) > 0.0
            else ""
        )
        + "</td>"
        f'<td class=num>{_gp(o["points"])}</td>'
        f'<td class=num>{_cp(_credit_points(o))}</td>'
        f'<td class="num {_slack_band(o.get("slack_fraction"))}">'
        f'{_pct(o.get("slack_fraction"))}</td>'
        f'<td class=num>{_num(o.get("clear_seconds"), 0) or "&mdash;"}</td></tr>'
        for o in p["optimal_summary"]
    )

    conflicts_html = ""
    if p["conflicts"]:
        items = "".join(f"<li>{html.escape(c)}</li>" for c in p["conflicts"])
        conflicts_html = (
            f'<p class="meta warn-text">Sign-up conflicts (multiple ticks): '
            f'resolved to the first drawn choice.</p><ul>{items}</ul>'
        )

    bench_html = (
        ", ".join(html.escape(n) for n in p["enforced_bench"])
        if p["enforced_bench"] else "(none — every uncommitted member found a seat)"
    )
    # Benched members are indexed too, pointing at the footnote that lists them.
    # Without this, searching for a real member who simply found no seat returns
    # "no member matches that name", which reads as "they are not in the guild".
    signup_index.extend(
        {"n": n, "t": "Not seated", "r": "bench-note"} for n in p["enforced_bench"]
    )
    # Escape "<" so the embedded JSON can never break out of its <script>.
    signup_json = json.dumps(signup_index, ensure_ascii=False).replace("<", "\\u003c")

    # --- Missing players: signed up but absent from the member roster -------
    # These ticked a trial but have no row on the member tab, so their skills
    # are unknown and they could not be placed. Surface them loudly (red) at the
    # top so officers immediately see who still needs to enter their data.
    missing = p.get("unmatched_signups") or []
    missing_html = ""
    missing_meta = ""
    if missing:
        chips = "".join(
            f'<span class="chip missing">{html.escape(n)}</span>' for n in missing
        )
        missing_html = f"""
  <section class="card danger" id="missing-data">
    <h2>&#9888; Signed up but missing from the roster ({len(missing)})</h2>
    <p class="meta">These player(s) ticked a trial on the
       <em>{html.escape(site.signup_tab)}</em> tab but have <strong>no row on the
       <em>{html.escape(site.member_tab)}</em> tab</strong>, so their skills are
       unknown and they could not be placed or benched. They need to add their
       data to the sheet before they can be assigned this week.</p>
    <p class="chips">{chips}</p>
  </section>"""
        missing_meta = (
            f' &middot; <span class="danger-text">{len(missing)} missing data</span>'
        )

    # --- Ineligible sign-ups: ticked a trial the game would refuse them ------
    # The 2026-08-11 patch gave each trial a minimum sign-up level. A volunteer below it
    # cannot actually sign up in game, so the plan does NOT lock them into that trial —
    # they fall into the uncommitted pool, where they may still be recommended for a
    # trial they do qualify for. Red, and modelled on #missing-data, because it means the
    # sheet and the game disagree: either the tick is stale or the minimum is new, and
    # an officer has to decide which.
    ineligible = p.get("ineligible_signups") or []
    ineligible_html = ""
    ineligible_meta = ""
    if ineligible:
        items = "".join(f"<li>{html.escape(m)}</li>" for m in ineligible)
        ineligible_html = f"""
  <section class="card danger" id="ineligible-signups">
    <h2>&#9888; Signed up below the trial's minimum level ({len(ineligible)})</h2>
    <p class="meta">These member(s) ticked a trial on the
       <em>{html.escape(site.signup_tab)}</em> tab whose <strong>minimum sign-up
       level the game would refuse</strong>, so the plan does not lock them into it.
       They are treated as <em>uncommitted</em> instead: the fill pass may still seat
       them in a trial they do qualify for, and they appear on the not-seated list if
       it cannot. Either the tick is stale or the minimum is newly set &mdash; the
       sheet and the game disagree, and only an officer can say which is right.</p>
    <ul>{items}</ul>
  </section>"""
        ineligible_meta = (
            f' &middot; <span class="danger-text">{len(ineligible)} below the '
            f'minimum level</span>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(site.title)} - Sign-up Optimiser</title>
<style>
  :root {{
    --bg: #0f1115; --panel: #171a21; --line: #2a2f3a;
    --text: #e6e8ec; --muted: #99a0ad; --accent: #6ea8fe;
    --on: #3ecf8e; --off: #3a3f4b; --warn: #e0b341; --danger: #f5645a;
    --assigned: #3ecf8e; --rec: #6ea8fe;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 2rem 1.25rem 4rem;
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text); }}
  header, main, footer {{ max-width: 1100px; margin-left: auto; margin-right: auto; }}
  header {{ margin-bottom: 1.5rem; }}
  h1 {{ margin: 0 0 .25rem; font-size: 1.6rem; letter-spacing: .5px; }}
  h2 {{ font-size: 1.15rem; margin: 0 0 .3rem; color: var(--accent); }}
  .meta {{ color: var(--muted); font-size: .85rem; }}
  .hl {{ color: var(--warn); }}
  .warn-text {{ color: var(--warn); }}
  .nav {{ margin: .5rem 0 0; font-size: .95rem; }}
  .nav a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
  .nav a:hover {{ text-decoration: underline; }}
  .strip {{ display: flex; flex-wrap: wrap; gap: .75rem; margin: 1.25rem 0 .5rem; }}
  .stat {{ flex: 1 1 180px; background: var(--panel); border: 1px solid var(--line);
           border-radius: 8px; padding: .75rem .9rem; }}
  .stat-skill {{ font-weight: 700; font-size: 1rem; }}
  .stat-tier {{ color: var(--accent); font-size: 1.7rem; font-variant-numeric: tabular-nums; }}
  .stat-pts {{ color: var(--muted); font-size: .85rem; }}
  .muted-text {{ color: var(--muted); font-weight: 400; }}
  .total {{ flex: 1 1 180px; background: #14251c; border: 1px solid var(--on);
            border-radius: 8px; padding: .75rem .9rem; }}
  .total .stat-tier {{ color: var(--on); }}
  .card {{ background: var(--panel); border: 1px solid var(--line);
           border-radius: 10px; padding: 1.1rem 1.2rem; margin: 1.5rem 0; }}
  .scroll {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }}
  table {{ border-collapse: collapse; width: 100%; background: var(--panel); }}
  th, td {{ padding: .4rem .6rem; border-bottom: 1px solid var(--line);
            text-align: left; white-space: nowrap; }}
  thead th {{ background: #1d222c; font-size: .78rem; text-transform: uppercase;
              letter-spacing: .4px; color: var(--muted); }}
  tbody th {{ font-weight: 600; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .cbadges {{ text-align: center; }}
  .badge {{ display: inline-grid; place-items: center; width: 16px; height: 16px;
            border-radius: 3px; font-size: 10px; font-weight: 700; margin: 0 1px; }}
  .badge.on {{ background: var(--on); color: #06231a; }}
  .badge.off {{ background: var(--off); color: #6b7180; }}
  /* Row colour-coding: green = signed up, blue = recommended fill. */
  tr.assigned > th, tr.assigned > td {{ background: rgba(62,207,142,.09);
     box-shadow: inset 3px 0 0 var(--assigned); }}
  tr.rec > th, tr.rec > td {{ background: rgba(110,168,254,.11);
     box-shadow: inset 3px 0 0 var(--rec); }}
  tbody tr:hover > th, tbody tr:hover > td {{ background: #1b2029; }}
  .chip {{ display: inline-block; padding: .05rem .5rem; border-radius: 999px;
           font-size: .75rem; font-weight: 700; }}
  .chip.assigned {{ background: rgba(62,207,142,.18); color: var(--on); }}
  .chip.rec {{ background: rgba(110,168,254,.20); color: var(--accent); }}
  .chip.filler {{ background: var(--off); color: #aab1c0; }}
  /* A fill that COSTS credit points (a rider seated under
     config.TRIAL_FILL_MAX_POINT_COST): amber, because it is a purchase, not a freebie. */
  .chip.cost {{ background: rgba(224,179,65,.20); color: var(--warn);
               border: 1px solid rgba(224,179,65,.45); }}
  .chip.swap {{ background: rgba(224,179,65,.20); color: var(--warn);
               text-transform: capitalize; }}
  .chip.reshuffle {{ background: rgba(110,168,254,.20); color: var(--accent);
               text-transform: capitalize; }}
  .chip.missing {{ background: rgba(245,100,90,.18); color: var(--danger);
               border: 1px solid rgba(245,100,90,.55); }}
  /* Safety swaps: green (they buy margin, never points), with overrides flagged. */
  .chip.safety {{ background: rgba(62,207,142,.18); color: var(--on);
               text-transform: capitalize; }}
  .chip.override {{ background: rgba(224,179,65,.16); color: var(--warn);
               border: 1px solid rgba(224,179,65,.45); margin-left: .3rem; }}
  .card.danger {{ border-color: var(--danger); background: #241618; }}
  .card.danger h2 {{ color: var(--danger); }}
  .danger-text {{ color: var(--danger); font-weight: 700; }}
  /* Time-margin bands (config.SLACK_THIN / SLACK_OK): green comfortable,
     amber thin, red knife-edge or nothing banked. The two-class rules exist
     because .stat-tier sets its own colour and is declared LATER than
     .warn-text — equal specificity there would let the accent blue win. */
  .ok-text {{ color: var(--on); }}
  .stat-tier.ok-text {{ color: var(--on); }}
  .stat-tier.warn-text {{ color: var(--warn); }}
  .stat-tier.danger-text {{ color: var(--danger); }}
  .chips {{ display: flex; flex-wrap: wrap; gap: .4rem; margin: .6rem 0 0; }}
  .swap-moves {{ margin: .35rem 0 0; padding-left: 1.1rem; font-size: .82rem;
               color: #aab1c0; }}
  .swap-moves li {{ margin: .1rem 0; }}
  /* --- Player search (mirrors the full-optimum page) -------------------- */
  .search {{ position: relative; max-width: 420px; margin: .25rem 0 1.25rem; }}
  .search input {{
    width: 100%; padding: .55rem .75rem; font: inherit;
    color: var(--text); background: var(--panel);
    border: 1px solid var(--line); border-radius: 8px;
  }}
  .search input:focus {{ outline: none; border-color: var(--accent); }}
  .search-results {{
    position: absolute; z-index: 5; left: 0; right: 0; margin-top: .3rem;
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 8px; overflow: hidden; box-shadow: 0 8px 24px rgba(0,0,0,.4);
  }}
  .sr-item {{
    display: flex; justify-content: space-between; align-items: center;
    gap: 1rem; width: 100%; padding: .45rem .7rem; font: inherit;
    text-align: left; color: var(--text); background: none; border: 0;
    border-bottom: 1px solid var(--line); cursor: pointer;
  }}
  .sr-item:last-child {{ border-bottom: 0; }}
  .sr-item:hover, .sr-item:focus {{ background: #1b2029; outline: none; }}
  .sr-name {{ font-weight: 600; }}
  .sr-trial {{ color: var(--accent); font-size: .85rem; }}
  .sr-empty {{ padding: .45rem .7rem; color: var(--muted); }}
  /* --- Row jump highlight ---------------------------------------------- */
  @keyframes rowflash {{
    0% {{ background: var(--accent); }}
    100% {{ background: transparent; }}
  }}
  /* Sign-up rows already carry a background from .assigned / .rec. No override is
     needed (and none may be used): a CSS animation outranks normal declarations
     while it runs, so the flash wins on its own — whereas a static
     `background: transparent !important` here would persist after the animation
     and strip the row of its status colour permanently. */
  tr.row-flash > th, tr.row-flash > td {{ animation: rowflash 1.8s ease-out; }}
  #bench-note.row-flash {{ animation: rowflash 1.8s ease-out; }}
  .legend {{ display: flex; gap: 1.25rem; flex-wrap: wrap; margin: .5rem 0 0;
             font-size: .82rem; color: var(--muted); }}
  .legend span {{ display: inline-flex; align-items: center; gap: .4rem; }}
  .sw {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; }}
  footer {{ margin-top: 2rem; color: var(--muted); font-size: .8rem; }}
  footer ol {{ padding-left: 1.2rem; }} footer li {{ margin: .25rem 0; }}
  code {{ background: #0b0d11; padding: 0 .3em; border-radius: 3px; }}
</style>
</head>
<body>
<header>
  <h1>Guild Trials &mdash; Sign-up Optimiser
      <span class="meta">(week of {html.escape(p['week_date'])})</span></h1>
  <p class="meta">{html.escape(site.title)} &middot; {p['roster_count']} members &middot;
     {p['signup_count']} signed up{missing_meta}{ineligible_meta} &middot; generated {html.escape(p['generated_at'])} (UTC)</p>
  <p class="nav"><a href="index.html">&larr; Skill Register</a>
     &nbsp;&middot;&nbsp; <a href="trials.html">Guild Trials (full optimum) &rarr;</a>
     &nbsp;&middot;&nbsp; <a href="{site.sibling_home}">{html.escape(site.sibling_title)} &rarr;</a></p>
</header>
<main>
  <div class="strip">{strip}</div>
  <p class="legend">
    <span><span class="sw" style="background:var(--assigned)"></span> Signed up (locked)</span>
    <span><span class="sw" style="background:var(--rec)"></span> Recommended fill (from the uncommitted pool)</span>
    <span><span class="sw" style="background:var(--warn)"></span> Swap (advisory)</span>
  </p>
  <p class="legend">Time margin:
    <span><span class="sw" style="background:var(--on)"></span> comfortable
      (&ge;&nbsp;{config.SLACK_OK * 100:.0f}% of the hour spare)</span>
    <span><span class="sw" style="background:var(--warn)"></span> thin
      (&lt;&nbsp;{config.SLACK_OK * 100:.0f}%)</span>
    <span><span class="sw" style="background:var(--danger)"></span> knife-edge
      (&lt;&nbsp;{config.SLACK_THIN * 100:.0f}%, or no tier banked)</span>
  </p>
  <div class="search">
    <input id="member-search" type="search" autocomplete="off"
           placeholder="Search a member&hellip; (jump to their trial &amp; row)"
           aria-label="Search for a guild member">
    <div id="search-results" class="search-results" role="listbox" hidden></div>
  </div>
  {missing_html}
  {ineligible_html}
  {cards_html}
  {swaps_section}
  {safety_section}

  <section class="card">
    <h2>Optimal (unconstrained) for comparison</h2>
    <p class="meta">The best possible teams over the full {p['roster_count']}-member roster,
       ignoring who signed up &mdash; the ceiling above. Full rosters on the
       <a href="trials.html">Guild Trials</a> page.</p>
    <div class="scroll">
      <table>
        <thead><tr><th>Trial</th><th class=num>Party</th>
          <th class=num>Tier</th><th class=num>Points</th>
          <th class=num>Credit pts</th>
          <th class=num>Margin</th><th class=num>Banked at (s)</th></tr></thead>
        <tbody>{opt_rows}</tbody>
      </table>
    </div>
  </section>
  {conflicts_html}
</main>
<footer>
  <h3>How this page is built</h3>
  <ol>
    <li><strong>Sign-ups are enforced.</strong> Every member who ticked a trial on
        the sheet's <em>SC Trial Signup</em> tab is locked into that trial and shown
        <span style="color:var(--on)">green</span>; they are never moved or benched
        in the plan.</li>
    <li><strong>Open seats are recommended fills.</strong> Remaining seats (up to the
        {p['cap']}-per-party cap) are offered to members who signed up for nothing
        &mdash; the {len(p['non_signups'])} uncommitted members &mdash; shown
        <span style="color:var(--accent)">blue</span>. A fill is only suggested where
        it does not <em>lower</em> a party's tier; ones that raise it are marked
        <code>Fill +pts</code>, harmless riders <code>Fill (safe)</code>.
        Uncommitted members with no useful seat: <span id="bench-note">{bench_html}</span>.</li>
    <li><strong>Swaps are advisory.</strong> The swap list is the minimal set of
        strictly-improving moves (each raising the score) from the enforced plan
        toward the full-roster optimum. Applying them overrides sign-ups.</li>
    <li><strong>Optimal is the ceiling.</strong> The optimum reuses the exact
        assignment the <a href="trials.html">Guild Trials</a> page computes, so the
        two never disagree. The scoring model, tiers and equipment assumptions are
        documented there.</li>
    <li><strong>A thin margin is no longer a fault &mdash; read this before
        worrying about one.</strong> Until 2026-08-11 points were a pure <em>step</em>
        function of the tier, so banking a tier with nine seconds left scored exactly
        the same as banking it with ten minutes, and a thin margin therefore meant
        something had gone wrong: the optimizer had no reason to cut it fine, and its
        safety pass deliberately widened it to around 15&ndash;18%.
        <br>
        Partial-tier credit changed the incentive. Completing a tier is still worth a
        {_num(config.TRIAL_POINTS_PER_TIER * (1 - config.TRIAL_PARTIAL_CREDIT_RATE), 0)}-point
        step, which is far more than any margin is worth, so the optimizer now
        <em>reaches</em> for tiers it can only just hold &mdash; and it is right to.
        Falling short no longer forfeits the tier: the party lands on the one below
        with almost all of its progress credited, so the downside is a handful of
        points rather than a hundred. On the live rosters that reaching is worth two
        extra tiers a week, bought at the price of margins measured in seconds.
        <br>
        So expect several trials to read <span class="danger-text">knife-edge</span>
        here, and read it as a deliberate bet rather than a blunder. Each card still
        shows when its last tier was <em>banked</em> out of the
        {_num(budget, 0)}-second budget, and the strip above still leads with the
        thinnest &mdash; those numbers now tell you <em>which</em> bets are outstanding,
        not that a mistake has been made. What they do not tell you is what the bet is
        worth, which is the next note.</li>
    <li><strong>The score on this page is the EXPECTED one.</strong> Since 2026-08-14
        the plan totals here &mdash; and the assignment itself &mdash; are chosen on
        <em>expected</em> credit points (<code>config.OPT_OBJECTIVE</code>): the score
        integrated over the calibrated shock, so a coin-flip tier contributes about
        half of itself and a comfortable one contributes all of it. The
        <em>deterministic</em> figure, what the lineup earns if every die lands on its
        expectation, rides alongside as the ceiling. It prices a tier held at even odds
        as a certainty and is therefore systematically <em>optimistic</em> exactly
        where the margins are thin, by {_pct(0.005)}&ndash;{_pct(0.010)} of the total
        or roughly {_num(24, 0)} points per knife-edge trial.
        <br>This inverts what the page used to say, and the reason is measured rather
        than aesthetic: optimising the deterministic score was documented as picking
        the same parties as optimising the expectation, and it does not. On the
        2026-08-14 roster one swap cost {_cp(0.867)} deterministic points and bought
        {_cp(8.736)} expected ones, taking a trial from
        {_num(0.3, 1)}s of spare time at even odds to {_num(31.8, 1)}s at
        {_pct(0.694)}. Plan against the expected figure; it is now also what the
        search plans against.</li>
    <li><strong>The margin, as odds.</strong> A margin is ordinal; officers plan
        against probabilities. Under a multiplicative shock on the party's work rate
        the clearing time scales with it, so
        <code>P = &Phi;(&minus;ln(1&minus;margin) / &sigma;)</code> &mdash; the margin
        enters as the <em>log of the slowdown the party can absorb</em>. &sigma; is
        computed per party: the per-action dice (derived exactly, Wald first passage,
        ~1.5&ndash;2%) added in quadrature to
        {config.RISK_SIGMA_SYSTEMATIC * 100:.1f}% for unmodelled gear &mdash; the neck,
        ring and earring slots the sheet has no column for, enhancement levels away
        from the assumed +7, and mis-ticked checkboxes. The map is steeply non-linear
        near the buzzer, which is why a margin that looks small can still be safe and
        why the two are shown together rather than one standing for the other.
        <strong>The figure is conditional on the assigned party turning up</strong> &mdash;
        this page says where to go and when to switch, not whether to appear &mdash; and
        it excludes sheet staleness, which can only make it conservative. It was checked
        against an independent simulation that rolls every action individually: predicted
        83%, realised 84% on the thinnest live lineup.</li>
    <li><strong>Safety swaps buy odds for at most
        {_cp(config.SIGNUP_SAFETY_POINTS_TOLERANCE)} points.</strong> The second swap
        list searches the same neighbourhood for moves that lift the thinnest trial
        without costing more than that &mdash; and at the shipped tolerance of
        {_cp(config.SIGNUP_SAFETY_POINTS_TOLERANCE)} it means the score does not fall at
        all, so the old promise of &ldquo;the same points&rdquo; still holds literally.
        The test used to be exact <em>equality</em> on the score; once partial-tier
        credit made points continuous, exact ties all but vanished and an equality test
        would have quietly found nothing to offer. A move that <em>gains</em> points is
        now welcome, because the independent requirement that the thinnest margin
        strictly rise is what forbids the failure the old rule was written against
        (a live probe once produced a move that gained a tier while crashing that
        trial's margin to 0.23%).
        <br>
        Note what this pass can and cannot do about the knife-edge trials described
        above: it can rearrange who sits where, but it cannot buy a comfortable margin
        by giving up a tier, because that costs far more than the tolerance allows. If
        every trial reads thin and this list is empty, nothing is broken &mdash; the
        lineup is taking bets the model judges worth taking. It spends the uncommitted members first (nothing
        overridden); only if that cannot reach {_pct(config.SIGNUP_SAFETY_TARGET)} does
        it propose moving a volunteer, and every such row is flagged. The list stops at
        {config.SIGNUP_SAFETY_MAX_MOVES} moves and each entry strictly improves on the
        one before, so applying a prefix is always valid.
        The list is <em>reported</em> in odds but <em>selected</em> on the margin, and
        the distinction is deliberate: the margin is where the guarantee lives (points
        exactly preserved, thinnest trial strictly raised), so ranking on the derived
        probability would buy nothing and could quietly change which moves ship. Both
        numbers are shown, because "83% &rarr; 97%" alone does not tell you whether that
        came from twelve seconds or two minutes.</li>
  </ol>
  <p>Any player who signed up but is <span class="danger-text">missing from the
     roster</span> is flagged in red near the top &mdash; they must add their data to
     the member tab before they can be assigned.</p>
  <p>Machine-readable copy of this page's data: <code>signup.json</code>.
     Static build from the public guild sheet; no credentials, read-only.</p>
</footer>
<script type="application/json" id="signup-data">{signup_json}</script>
<script>{_SIGNUP_JS}</script>
</body>
</html>
"""


def _render_signup_inactive_html(reason: str, generated_at: str, site: "GuildSite") -> str:
    """Render a graceful placeholder for the sign-up optimiser page.

    Emitted when the live "SC Trial Signup" tab no longer matches the expected
    tick-box layout (a :class:`SheetStructureError` from ``parse_signup``) — e.g.
    the guild switched to *free-assigned* trials and repurposed the tab. This is
    an upstream DATA change, not a build failure, so the build stays green and
    still ships this page: the nav links on the other pages keep resolving (no
    404) and a visitor gets an honest explanation. The real optimiser page
    returns automatically once a parseable sign-up tab is published again.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(site.title)} - Sign-up Optimiser</title>
<style>
  :root {{ --bg:#0f1115; --panel:#171a21; --line:#2a2f3a; --text:#e6e8ec;
    --muted:#99a0ad; --accent:#6ea8fe; --warn:#e0b341; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:2rem 1.25rem 4rem;
    font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background:var(--bg); color:var(--text); }}
  header, main {{ max-width:1100px; margin:0 auto; }}
  header {{ margin-bottom:1.5rem; }}
  h1 {{ margin:0 0 .25rem; font-size:1.6rem; letter-spacing:.5px; }}
  h2 {{ font-size:1.15rem; margin:0 0 .3rem; color:var(--warn); }}
  .meta {{ color:var(--muted); font-size:.85rem; }}
  .nav {{ margin:.5rem 0 0; font-size:.95rem; }}
  .nav a {{ color:var(--accent); text-decoration:none; font-weight:600; }}
  .nav a:hover {{ text-decoration:underline; }}
  .card {{ background:var(--panel); border:1px solid var(--line);
    border-radius:10px; padding:1.1rem 1.2rem; margin:1.5rem 0; }}
  code {{ background:#0b0d11; padding:0 .3em; border-radius:3px;
    word-break:break-word; }}
  p {{ margin:.6rem 0; }}
</style>
</head>
<body>
<header>
  <h1>Guild Trials &mdash; Sign-up Optimiser</h1>
  <p class="meta">{html.escape(site.title)} &middot; generated {html.escape(generated_at)} (UTC)</p>
  <p class="nav"><a href="index.html">&larr; Skill Register</a>
     &nbsp;&middot;&nbsp; <a href="trials.html">Guild Trials (full optimum) &rarr;</a>
     &nbsp;&middot;&nbsp; <a href="{site.sibling_home}">{html.escape(site.sibling_title)} &rarr;</a></p>
</header>
<main>
  <section class="card">
    <h2>Sign-up optimiser is currently inactive</h2>
    <p>This page enforces the guild's per-member trial sign-ups (the tick-box
       <em>SC Trial Signup</em> tab) and recommends fills for the open seats. It is
       paused because that sign-up table is not currently published in the
       expected format:</p>
    <p class="meta"><code>{html.escape(reason)}</code></p>
    <p>The guild sheet presently runs trials as <strong>free-assigned</strong>
       (members pick their own trial), so there is no tick-box sign-up table to
       enforce. This page repopulates automatically once a parseable
       <em>SC Trial Signup</em> tab exists again.</p>
    <p>In the meantime, the <a href="trials.html">Guild Trials</a> page shows the
       full-roster optimal assignment.</p>
  </section>
</main>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# The build, fanned out across processes
# ---------------------------------------------------------------------------
# WHY THIS IS NOT ONE SERIAL PASS ANY MORE (2026-08-14).
#
# The build had grown from 5m25s to 16m35s on the runner, and every second of it
# was spent one after another. Measured per phase on live rosters:
#
#              run_week L1   run_week L20   signup.plan   total
#   SC              84.8s          90.8s        18.6s    194.6s
#   LI              56.2s          95.1s       ~18.0s   ~170.0s
#
# Two things had landed: the 2026-08-11 partial-credit patch (which cost little)
# and the level-20 counterfactual page (which very nearly DOUBLED the work, because
# it is a second complete optimiser run per guild — and a dearer one, since at
# level-20 buffs the parties reach higher tiers and every simulate_race in the hot
# loop runs longer; note LI's L20 costs 69% more than its L1).
#
# But those four optimiser runs are mutually independent, and the runner has four
# vCPUs (GitHub gives public repositories 4-vCPU/16GiB machines, with unlimited free
# Actions minutes — the "~2000 minutes/month" worry this file's cron comment used to
# carry did not apply to a public repo). So the units run concurrently and the
# critical path becomes max(L1+signup, L20) per guild rather than the sum of
# everything: ~103s against ~365s locally.
#
# SINCE 2026-08-14 there are TWO units, not four: the counterfactual is off and the
# buff selector re-rates the published plan instead, which costs 0.20s per guild for
# all twenty rungs — four orders of magnitude under the ~90s run it replaced (each
# rung is score_assignment alone, no search). The fan-out stays because it still
# earns its keep on two units, and because the counterfactual is one config line
# from returning to four.
#
# THE OUTPUT IS UNCHANGED, BIT FOR BIT. Every seed is fixed
# (config.TRIAL_OPTIMIZER_SEED, and _run_ensemble's derived seed + 1 + i), each unit
# reads only its own inputs, and ties are settled by a canonical party key — so no
# result depends on execution order or on which unit finishes first.
#
# PROCESSES, NOT THREADS, and this is not a preference. The counterfactual runs under
# trials.community_buff_level, which REBINDS module globals on config (see its
# docstring: "NOT thread-safe, and not intended to be"). Two regimes in one
# interpreter would corrupt each other's rate model. Separate processes each get their
# own copy of config, which is exactly the isolation that context manager assumes.
#
# THE ROSTER IS FETCHED ONCE, IN THE PARENT, and handed down. That is not merely to
# save requests: it guarantees both regimes of a guild see ONE snapshot of the sheet.
# Were each child to fetch for itself, an officer editing the member tab mid-build
# could make trials.html and trials-maxbuffs.html disagree about who is in the guild.
#
# RENDERING STAYS IN THE PARENT because each trials page's regime switch carries the
# OTHER page's level and total, so neither can be written until both units are done.
# It is string work and costs nothing.
#
# config.BUILD_PARALLEL = False is the one-line rollback: the same units, run
# serially in this process, for when a traceback needs to be read in peace.
@dataclass
class _GuildInputs:
    """One guild's fetched inputs — everything the compute units need.

    Assembled in the parent (all network, ~1s) so the children are pure CPU and the
    whole guild is provably reading one snapshot of the sheet.
    """

    site_key: str
    # The guild's roster from its member tab: the input to BOTH regimes and to the
    # sign-up plan. A list of plain dataclasses, hence picklable.
    members: list[MemberRow]
    # process() output for index.html / data.json (written by the parent — cheap).
    register: dict
    # {member_name: {sheet_skill_names_ticked}}, or None when the sign-up plan
    # cannot be built at all (see signup_unavailable).
    picks: Optional[dict[str, set[str]]]
    # Empty when picks is usable; otherwise the reason, rendered onto an inactive
    # signup.html so the nav stays valid and the page says why it cannot help.
    signup_unavailable: str = ""
    # The same reason in a few words, for the one-line CI summary. Carried separately
    # rather than truncated from the long form, which contains skill names with dots
    # in them ("C.Smithing") and does not survive being cut at the first period.
    signup_unavailable_short: str = ""
    # Per-guild roster provenance (roster.Provenance), or None when the roster was
    # not consulted at all — config.ROSTER_SOURCE_ENABLED off, or the fetch failed.
    # Counts only; picklable like everything else here.
    roster_provenance: Optional["roster_model.Provenance"] = None
    # Non-empty when the roster tab could not be read: the reason, for the warning
    # and the on-page banner. The build still ships, from the manual tab.
    roster_unavailable: str = ""
    # Filled by main() in the render phase from the published unit's result. Not an
    # input — it lives here so one object carries everything _write_guild needs.
    plan_dict: Optional[dict] = None


def _report_roster_join(
    site: "GuildSite", prov: "roster_model.Provenance"
) -> None:
    """Print the roster join's NOTE/WARNING pair, beside the sign-up ones.

    Every one of these is actionable by an officer, which is why none of them is
    swallowed — the same discipline the sign-up join already applies.
    """
    if prov.refused:
        print(f"WARNING ({site.key}): roster REFUSED — {prov.refused}", file=sys.stderr)
        return

    print(
        f"NOTE ({site.key}): roster join {prov.roster_backed}/"
        f"{prov.roster_backed + prov.manual_backed} members, captured "
        f"{prov.captured_at or 'unknown'}; {len(prov.gear_hidden)} hide their gear "
        f"(tools from the '{site.member_tab}' tab).",
        file=sys.stderr,
    )
    if prov.normalized_matches:
        print(
            f"NOTE ({site.key}): {len(prov.normalized_matches)} roster name(s) "
            f"matched a member only after case/space normalisation "
            f"(tidy the '{site.member_tab}' tab): "
            + "; ".join(prov.normalized_matches),
            file=sys.stderr,
        )
    if prov.unmatched_members:
        print(
            f"NOTE ({site.key}): {len(prov.unmatched_members)} member(s) match NO "
            f"roster row and keep the '{site.member_tab}' tab's data: "
            + ", ".join(prov.unmatched_members),
            file=sys.stderr,
        )
    if prov.admitted:
        print(
            f"NOTE ({site.key}): {prov.admitted} member(s) exist ONLY on the "
            f"'{site.roster_tab}' tab and were SEATED from it — before this change "
            f"they were dropped entirely, because the '{site.member_tab}' tab has "
            f"never heard of them: {', '.join(prov.admitted_names)}. They carry no "
            f"Top/Bot checkboxes (the roster does not record body or legs), so "
            f"their rates are if anything understated. Adding them to the member "
            f"tab is still the right fix.",
            file=sys.stderr,
        )
    if prov.reported_not_seated:
        print(
            f"WARNING ({site.key}): {len(prov.reported_not_seated)} roster name(s) "
            f"are on the '{site.roster_tab}' tab but NOT on the "
            f"'{site.member_tab}' tab and were NOT seated "
            f"(config.ROSTER_ADMITS_NEW_MEMBERS is False): "
            + ", ".join(prov.reported_not_seated),
            file=sys.stderr,
        )
    if prov.ambiguous:
        print(
            f"WARNING ({site.key}): {len(prov.ambiguous)} name(s) are ambiguous "
            f"after normalisation and joined to NOBODY: "
            + ", ".join(prov.ambiguous),
            file=sys.stderr,
        )


def _fetch_guild(site: "GuildSite", week_draw: "draw_model.TrialDraw") -> _GuildInputs:
    """Fetch one guild's sheet inputs and validate its sign-up tab against the draw.

    Raises:
        SheetStructureError: if the guild's MEMBER tab no longer matches its layout
            (fatal for a required guild — there is no page without a roster).
        RuntimeError: on any network/HTTP failure.
    """
    # Survey Corps reads the gid=0 published register; every other guild has no such
    # gid export, so its register is built from the gviz member tab (which the trials
    # step reuses, so that tab is fetched only once per guild).
    if site.use_register_csv:
        register = process(parse(fetch_csv()))
    else:
        register = None  # filled from the member tab below

    gd = scrape_member_tab(site.member_tab)
    if register is None:
        register = process(gd.members)

    # --- The roster tab, and the merge ------------------------------------------
    # THE REGISTER IS BUILT FIRST, AND FROM THE UNMERGED ROWS, deliberately.
    # index.html mirrors the officers' own hand-maintained tab, stale cells and all;
    # that is the page an officer uses to NOTICE a stale cell. trials.html and
    # signup.html are the model and take the merged rows. The two pages answer
    # different questions and conflating them would destroy the one that reports
    # data quality.
    #
    # GATED AT THE FETCH rather than at the consumers: with
    # config.ROSTER_SOURCE_ENABLED off the build does not even talk to the roster
    # tab, so the rollback also covers the case where the separate Apps Script
    # deployment is the thing that is broken.
    members = gd.members
    roster_provenance = None
    roster_unavailable = ""
    if config.ROSTER_SOURCE_ENABLED:
        try:
            roster_rows = roster_model.scrape_roster_tab(site.roster_tab)
        except SheetStructureError as exc:
            # DEGRADE, do not stop the deploy. The roster tab is written by a
            # SEPARATE Apps Script deployment whose header shifts when a module
            # toggle moves, and nobody who moves that toggle is thinking about this
            # pipeline. SC is required=True, so an uncaught raise here would take
            # down every page of BOTH guilds.
            #
            # The INCIDENT 2026-08-14 counter-example (a quiet fallback shipping
            # wrong advice) does not apply: there the fallback was a stale CONSTANT,
            # here it is today's shipped behaviour — the status quo ante, already
            # believed good enough to publish this morning. A network RuntimeError
            # still propagates and fails the build, exactly as elsewhere.
            roster_unavailable = (
                f"The {site.roster_tab!r} tab could not be read, so every member's "
                f"data comes from the '{site.member_tab}' tab instead. Reason: {exc}"
            )
            print(
                f"WARNING ({site.key}): roster unavailable, falling back to the "
                f"manual member tab:\n{exc}",
                file=sys.stderr,
            )
        else:
            report = roster_model.join(gd.members, roster_rows)
            members, roster_provenance = roster_model.merge(
                gd.members, report, site.key
            )
            _report_roster_join(site, roster_provenance)

    # --- The sign-up tab, and whether it is talking about THIS week --------------
    # A SheetStructureError here means this guild's sign-up tab no longer carries the
    # tick-box sign-up table (e.g. trials went "free-assigned" and the tab was
    # repurposed — see the 2026-07 reformat). That is an upstream DATA change, not a
    # build failure: the guild still gets its member and trials pages and an inactive
    # signup.html. A network/HTTP RuntimeError still propagates and fails loudly.
    picks: Optional[dict[str, set[str]]] = None
    unavailable = ""
    unavailable_short = ""
    try:
        signup_csv = signup_model.fetch_signup_csv(site.signup_tab)
        tab_skills = draw_model.trial_columns(signup_csv, site.signup_tab)

        # THE STALENESS GUARD, added 2026-08-14 after the case that motivated it.
        # The game rewrites each guild's sign-up tab when a new cycle opens, and it
        # does not do so for both guilds at once. On 2026-08-14 the LI tab still held
        # the ENTIRE 8/10 cycle — its four skills AND both its combat bosses — while
        # SC's had moved on to 8/14. Nothing noticed, because parse_signup validates
        # that the four headers are SKILLS and every one of last week's was.
        #
        # So a plan was being built from the wrong week's volunteers and published as
        # this week's advice. That is worse than no plan: an officer cannot tell it
        # apart from a good one. The plan is therefore WITHHELD when a guild's own
        # sign-up columns disagree with the draw, and the page says so.
        #
        # Compared as SETS, not sequences: the game orders these columns as it likes
        # and the draw carries no priority (see draw.TrialDraw), so order is not
        # information and a re-ordering must not be mistaken for a stale week.
        if set(tab_skills) != set(week_draw.skills):
            unavailable = (
                f"The {site.signup_tab!r} tab lists "
                f"{', '.join(tab_skills)}, which is not this week's draw "
                f"({', '.join(week_draw.skills)}). The game refreshes each guild's "
                f"sign-up tab when a new cycle opens and has not yet refreshed this "
                f"one, so its ticks are a PREVIOUS week's volunteers. A plan built "
                f"from them would be indistinguishable from a good one, so none is "
                f"published; it returns by itself once the tab catches up."
            )
            unavailable_short = (
                f"stale tab, lists [{', '.join(tab_skills)}]"
            )
        else:
            picks = signup_model.parse_signup(signup_csv, tab_label=site.signup_tab)
    except SheetStructureError as exc:
        unavailable = str(exc)
        unavailable_short = f"{site.signup_tab} not in tick-box sign-up format"

    if unavailable:
        print(
            f"WARNING ({site.key}): sign-up plan withheld — {unavailable}",
            file=sys.stderr,
        )

    return _GuildInputs(
        site_key=site.key,
        members=members,
        register=register,
        picks=picks,
        signup_unavailable=unavailable,
        signup_unavailable_short=unavailable_short,
        roster_provenance=roster_provenance,
        roster_unavailable=roster_unavailable,
    )


def _compute_unit(job: dict) -> dict:
    """Run ONE optimiser unit. The child-process entry point.

    Module-level and taking/returning only plain data, so it pickles by reference
    under both the ``fork`` and ``spawn`` start methods.

    ``job["level"]`` is None for the PUBLISHED regime (whatever
    config.COMMUNITY_BUFF_LEVEL says) or a ladder level for a counterfactual, run
    inside trials.community_buff_level — which is why this must be a process of its
    own rather than a thread (that context manager rebinds config globals).

    ``job["picks"]`` is None for a counterfactual unit and the parsed sign-up ticks
    for the published one. The sign-up plan is deliberately computed HERE, in the same
    unit as the published week, because it needs that week's WeekResult object as its
    optimal ceiling (signup.optimal_from_week) — keeping the two together avoids
    shipping a large object between processes and keeps the two pages agreeing on the
    ceiling by construction.
    """
    level = job["level"]
    members = job["members"]
    skills = job["skills"]
    min_levels = job["min_levels"]
    cap = job["cap"]

    ladder: dict = {}
    if level is None:
        # The published unit also rates its own plan at every rung of the buff
        # ladder, for the page's level selector. It is the SAME search — one
        # optimize() call, twenty score_assignment() calls at ~2ms each — so the
        # ladder is free beside the unit that carries it, and could not be computed
        # anywhere else without redoing the search or shipping the parties between
        # processes.
        if config.TRIALS_BUFF_LEVEL_SLIDER:
            week, rungs = trials_model.run_week_ladder(
                members, skills=skills, cap=cap, min_levels=min_levels
            )
            ladder = {str(k): v.to_dict() for k, v in rungs.items()}
        else:
            week = trials_model.run_week(
                members, skills=skills, cap=cap, min_levels=min_levels
            )
    else:
        with trials_model.community_buff_level(level):
            week = trials_model.run_week(
                members, skills=skills, cap=cap, min_levels=min_levels
            )

    out: dict = {"week": week.to_dict(), "ladder": ladder}

    picks = job["picks"]
    if picks is not None:
        optimal_total, optimal_summary = signup_model.optimal_from_week(week)
        plan = signup_model.plan(
            members, picks, optimal_total, optimal_summary,
            cap=cap, min_levels=min_levels, draw=skills,
        )
        out["plan"] = plan.to_dict()
    return out


def _summary_line(
    site: "GuildSite",
    inputs: _GuildInputs,
    week: dict,
    week_maxbuff: Optional[dict],
    week_draw: "draw_model.TrialDraw",
) -> str:
    """The one-line per-guild CI summary.

    Quotes CREDIT points (one decimal — these are floats now) with the step total
    beside them, so a CI log tells you both what the plan was chosen on and what the
    guild will see banked in game. Truncating to int here would silently hide every
    partial-credit difference the whole 2026-08-11 patch exists to expose.
    """
    # What the maxed-buff counterfactual scored, and the gap — so a CI log records the
    # size of the whole week's buff sensitivity, not just this regime's total.
    maxbuff_note = (
        f" vs L{week_maxbuff['community_buff_level']} "
        f"{week_maxbuff['total_credit_points']:,.1f} cp "
        f"({week_maxbuff['total_credit_points'] - week['total_credit_points']:+,.1f})"
        if week_maxbuff is not None
        else " (maxbuff page off)"
    )

    plan = inputs.plan_dict
    if plan is None:
        signup_note = f"WITHHELD — {inputs.signup_unavailable_short}"
    else:
        # Every figure here is in the OBJECTIVE's currency and suffixed "E" to say so —
        # the enforced total, the reachable one and the ceiling alike. They used to be
        # credit ("cp"); the suffix moved with the objective rather than being dropped,
        # because the one number on this line with no unit was the one that silently
        # changed meaning. The step totals stay "pts": those are the banked tiers.
        signup_note = (
            f"{plan['signup_count']} signed, enforced "
            f"{plan['enforced_total']:,.1f} E "
            f"({plan['enforced_step_total']} pts) "
            f"-> {plan['reachable_total']:,.1f} E via {len(plan['swaps'])} swap(s) "
            f"(optimal {plan['optimal_total']:,.1f} E / "
            f"{plan['optimal_step_total']} pts); "
            f"{len(plan['ineligible_signups'])} below min level, "
            f"{len(plan['normalized_matches'])} case-fixed, "
            f"{len(plan['unmatched_signups'])} unmatched"
        )

    dest = f"_site/{site.subdir}/" if site.subdir else "_site/"
    return (
        f"[{site.key}] {dest} {inputs.register['member_count']} members "
        f"({len(inputs.register['skills'])} skills); draw {week_draw.date or '?'} "
        f"[{', '.join(week_draw.skills)}]; trials "
        + ", ".join(
            f"{t['skill']} T{t['tier_reached']}+{t['partial_fraction'] * 100:.0f}%/"
            f"{t['credit_points']:,.1f}cp"
            for t in week["trials"]
        )
        + f" (total {week['total_credit_points']:,.1f} cp / {week['total_points']} pts); "
        f"buffs L{week['community_buff_level']}{maxbuff_note}; "
        f"signup: {signup_note}"
    )


def _write_guild(
    site: "GuildSite",
    inputs: _GuildInputs,
    week: dict,
    week_maxbuff: Optional[dict],
    week_draw: "draw_model.TrialDraw",
    draw_warning: str,
    ladder: Optional[dict] = None,
) -> str:
    """Write one guild's pages from its already-computed results; return the summary.

    Pure rendering and file I/O — no optimiser work happens here, which is why it can
    wait until every unit has landed without costing anything.
    """
    out = site.out_dir
    out.mkdir(parents=True, exist_ok=True)

    # --- Member skill register (index.html + data.json) ---------------------
    (out / "data.json").write_text(
        json.dumps(inputs.register, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out / "index.html").write_text(
        _render_html(inputs.register, site), encoding="utf-8"
    )

    # --- Guild Trials: the published regime and its counterfactual -----------
    # Each page's switch points at the other, carrying the other's level and total so
    # the reader can see what the alternative regime is worth before navigating. That
    # mutual reference is why both pages are written here rather than in the units.
    (out / TRIALS_JSON).write_text(
        json.dumps(week, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out / TRIALS_PAGE).write_text(
        _render_trials_html(
            week, site, draw_warning,
            counterpart=(
                {
                    "href": TRIALS_MAXBUFF_PAGE,
                    "level": week_maxbuff["community_buff_level"],
                    "total": week_maxbuff["total_credit_points"],
                }
                if week_maxbuff is not None
                else None
            ),
            ladder=ladder,
        ),
        encoding="utf-8",
    )
    if week_maxbuff is None:
        # Take the counterfactual DOWN with its switch when it is not published.
        # CI builds into a fresh checkout so this is a no-op there, but a local
        # rebuild would otherwise leave the previous run's pages sitting at their
        # own URLs, unlinked and quietly stale — the same trap signup.json carries
        # below, and the same fix. missing_ok: there may never have been one.
        (out / TRIALS_MAXBUFF_PAGE).unlink(missing_ok=True)
        (out / TRIALS_MAXBUFF_JSON).unlink(missing_ok=True)
    else:
        (out / TRIALS_MAXBUFF_JSON).write_text(
            json.dumps(week_maxbuff, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out / TRIALS_MAXBUFF_PAGE).write_text(
            _render_trials_html(
                week_maxbuff, site, draw_warning,
                counterpart={
                    "href": TRIALS_PAGE,
                    "level": week["community_buff_level"],
                    "total": week["total_credit_points"],
                },
            ),
            encoding="utf-8",
        )

    # --- Sign-up Optimiser (OPTIONAL) ---------------------------------------
    plan = inputs.plan_dict
    if plan is None:
        (out / "signup.html").write_text(
            _render_signup_inactive_html(
                inputs.signup_unavailable,
                datetime.now(timezone.utc).isoformat(),
                site,
            ),
            encoding="utf-8",
        )
        # And take the machine-readable copy DOWN with the page. CI always builds into
        # a fresh checkout so this is a no-op there, but a local rebuild (or any future
        # incremental deploy) would otherwise leave the previous run's signup.json
        # sitting beside a page that says there is no plan — the one artefact a reader
        # or script could still pick up and act on. missing_ok: there may never have
        # been one.
        (out / "signup.json").unlink(missing_ok=True)
    else:
        (out / "signup.json").write_text(
            json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out / "signup.html").write_text(
            _render_signup_html(plan, site), encoding="utf-8"
        )

        # Data-quality signals from the sign-up name join. Case/space-only
        # disagreements are matched automatically but reported so the sheet can be
        # tidied; a sign-up that matches NO member is silently unusable, so it is a
        # loud WARNING (it points either at a typo or a missing member row).
        if plan["normalized_matches"]:
            print(
                f"NOTE ({site.key}): {len(plan['normalized_matches'])} sign-up "
                f"name(s) matched a member only after case/space normalisation "
                f"(tidy the '{site.member_tab}' tab): "
                + "; ".join(plan["normalized_matches"]),
                file=sys.stderr,
            )
        if plan["unmatched_signups"]:
            print(
                f"WARNING ({site.key}): {len(plan['unmatched_signups'])} sign-up "
                f"name(s) match NO member on the '{site.member_tab}' tab and were "
                f"IGNORED: {', '.join(plan['unmatched_signups'])}. Fix the spelling "
                f"in the sheet or add the member.",
                file=sys.stderr,
            )

    return _summary_line(site, inputs, week, week_maxbuff, week_draw)


def _load_draw() -> tuple["draw_model.TrialDraw", str]:
    """Read this week's draw, or fall back to the last known one behind a warning.

    A STRUCTURE failure here used to be fatal, on the reasoning that a stale draw is
    worse than no page. INCIDENT 2026-07-25 showed the cost of that trade: a layout
    change stopped the whole deploy, every page of every guild. So it degrades — the
    site ships with a loud on-page banner instead.

    INCIDENT 2026-08-14 showed the cost of THIS trade, and it is worth stating beside
    the other: the officers rebuilt the source tab, the parser found nothing, and the
    site optimised config.TRIAL_SKILLS_CURRENT — the wrong four trials — for a day
    behind that banner. The banner is what got it noticed, so the mechanism worked;
    but note that the fallback's job is only to keep the OTHER pages shipping, and it
    is not a substitute for the draw. Both incidents point the same way: read the
    draw from the tab the GAME writes (draw.py now does) and keep the fallback loud.

    A network/HTTP RuntimeError still propagates and fails the build.
    """
    try:
        return draw_model.load_draw(), ""
    except SheetStructureError as exc:
        warning = (
            f"This week's draw could not be read from the "
            f"{draw_model.DRAW_TAB!r} tab, so the last known draw "
            f"({', '.join(config.TRIAL_SKILLS_CURRENT)}) is shown instead and MAY "
            f"BE STALE. Reason: {exc}"
        )
        print(
            f"WARNING: trial draw unreadable, falling back to "
            f"config.TRIAL_SKILLS_CURRENT:\n{exc}",
            file=sys.stderr,
        )
        return (
            draw_model.TrialDraw(
                skills=list(config.TRIAL_SKILLS_CURRENT), date="unknown"
            ),
            warning,
        )


def _unit_jobs(site: "GuildSite", inputs: _GuildInputs, week_draw) -> list[dict]:
    """The independent optimiser units for one guild, published regime first.

    ONE unit per guild as shipped: the published week, which also carries the sign-up
    plan (because it owns the WeekResult that plan's ceiling is read from) and the
    inline buff ladder (because it owns the assignment every rung re-rates).

    config.TRIALS_PUBLISH_MAXBUFF_PAGE = True adds a second: the maxed-buff
    counterfactual, a complete re-optimisation rather than a re-rating, and the
    dearer of the two runs. It is off by default — measured on the 2026-08-14 live
    rosters, re-optimising at level 20 beat re-rating there by 4.2 points on SC and
    0.6 on LI, out of ~4,950, and moved no trial to a different tier.
    """
    common = {
        "site_key": site.key,
        "members": inputs.members,
        "skills": week_draw.skills,
        "min_levels": week_draw.min_levels,
        # THIS guild's seat cap (config.TRIAL_PARTY_CAPS), resolved here in the
        # parent and shipped with the job rather than looked up in the child: the
        # unit is plain data by contract, and a child re-deriving it from a key
        # would be a second place for the mapping to be read.
        "cap": site.party_cap,
    }
    jobs = [{**common, "level": None, "picks": inputs.picks}]
    if config.TRIALS_PUBLISH_MAXBUFF_PAGE:
        jobs.append(
            {**common, "level": config.COMMUNITY_BUFF_MAX_LEVEL, "picks": None}
        )
    return jobs


def _run_units(jobs: list[dict]) -> list[dict]:
    """Run every unit and return the results in the order the jobs were given.

    Concurrent across ALL guilds, not merely within one: with four units of 56–95s
    each, synchronising on a per-guild barrier would idle a core waiting for that
    guild's slower half. The pool is sized to the smaller of the units and the
    machine, so a 2-vCPU runner degrades to two-at-a-time rather than thrashing.
    """
    if not config.BUILD_PARALLEL or len(jobs) == 1:
        return [_compute_unit(job) for job in jobs]

    workers = min(len(jobs), config.BUILD_MAX_WORKERS or (os.cpu_count() or 1))
    with futures.ProcessPoolExecutor(max_workers=workers) as pool:
        # Submitted in order and read back in order: map() would do, but submit()
        # lets an exception surface against the job that caused it.
        pending = [pool.submit(_compute_unit, job) for job in jobs]
        return [f.result() for f in pending]


def main() -> int:
    """Build every guild's site into ``_site`` (Survey Corps at the root, the rest in
    sub-directories). A ``required`` guild's failure is fatal (non-zero exit blocks
    the atomic Pages deploy); an optional guild's failure is a warning so the others
    still ship.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # One draw, shared by every guild (see config.DRAW_SOURCE_TAB on why it is read
    # from Survey Corps' game-written sign-up tab and not per guild).
    week_draw, draw_warning = _load_draw()

    # --- Phase 1: fetch (parent, network-bound, ~1s per guild) --------------
    fetched: list[tuple[GuildSite, _GuildInputs]] = []
    for site in GUILD_SITES:
        try:
            fetched.append((site, _fetch_guild(site, week_draw)))
        except SheetStructureError as exc:
            if site.required:
                print(
                    f"ERROR: sheet structure mismatch ({site.key}):\n{exc}",
                    file=sys.stderr,
                )
                return 2
            print(
                f"WARNING: {site.key} skipped (sheet structure mismatch); "
                f"other guilds continue:\n{exc}",
                file=sys.stderr,
            )
        except RuntimeError as exc:
            if site.required:
                print(f"ERROR ({site.key}): {exc}", file=sys.stderr)
                return 1
            print(
                f"WARNING: {site.key} skipped ({exc}); other guilds continue.",
                file=sys.stderr,
            )

    # --- Phase 2: optimise (children, CPU-bound, the whole cost of the build) ---
    jobs: list[dict] = []
    spans: list[tuple[GuildSite, _GuildInputs, int, int]] = []
    for site, inputs in fetched:
        site_jobs = _unit_jobs(site, inputs, week_draw)
        spans.append((site, inputs, len(jobs), len(jobs) + len(site_jobs)))
        jobs.extend(site_jobs)

    results = _run_units(jobs)

    # --- Phase 3: render (parent — both regimes must be in hand) ------------
    notes: list[str] = []
    for site, inputs, start, end in spans:
        span = results[start:end]
        week = span[0]["week"]
        inputs.plan_dict = span[0].get("plan")
        week_maxbuff = span[1]["week"] if len(span) > 1 else None
        notes.append(
            _write_guild(
                site, inputs, week, week_maxbuff, week_draw, draw_warning,
                ladder=span[0].get("ladder") or None,
            )
        )

    print("Built _site/:")
    for note in notes:
        print("  " + note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
