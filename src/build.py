"""Entry point: fetch -> parse -> process -> write static site into _site/.

Run with:  python -m src.build

Exits non-zero on any fetch/parse/structure error so CI fails loudly.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from . import config
from . import signup as signup_model
from . import trials as trials_model
from .processor import process
from .reader import SheetStructureError, fetch_csv, parse
from .scraper import scrape_member_tab

OUTPUT_DIR = Path("_site")


def _badge(present: bool, label: str) -> str:
    """Render a small T/T/B style badge; filled when present, muted when not."""
    cls = "badge on" if present else "badge off"
    return f'<span class="{cls}" title="{html.escape(label)}">{label[0]}</span>'


def _render_html(data: dict) -> str:
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
<title>SURVEY CORPS - Skill Register</title>
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
  <h1>SURVEY CORPS &mdash; Skill Register</h1>
  <p class="meta">Milky Way Idle guild &middot; {data['member_count']} members &middot;
     generated {html.escape(data['generated_at'])} (UTC)</p>
  <p class="nav"><a href="trials.html">Guild Trials &rarr;</a>
     &nbsp;&middot;&nbsp; <a href="signup.html">Sign-up Optimiser &rarr;</a></p>
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


def _sorted_roster(trial: dict) -> list[dict]:
    """Roster pre-sorted by rate at the final tier, descending (default sort).

    This is the server-side render order for the roster table; the client-side
    sorter's initial arrow state reflects the same default (see the page JS).
    """
    return sorted(trial["roster"], key=lambda r: r["rate_final"], reverse=True)


def _render_trial_card(trial: dict, t_index: int) -> tuple[str, list[dict]]:
    """Render one trial's section and return (html, assignment_entries).

    ``assignment_entries`` maps each rostered member to this trial and to the
    DOM id of their (pre-sorted) roster row, feeding the page's player search.
    """
    skill = html.escape(trial["skill"])
    final_tier = trial["tier_reached"] if trial["tier_reached"] >= 1 else 1

    roster = _sorted_roster(trial)
    assign_entries = [
        {"n": r["name"], "t": trial["skill"], "r": f"r-{t_index}-{i}"}
        for i, r in enumerate(roster)
    ]

    roster_rows = "".join(
        f'<tr id="r-{t_index}-{i}">'
        f"<th scope=row>{html.escape(r['name'])}</th>"
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

    timeline_rows = "".join(
        "<tr class=\"{cls}\">"
        "<td class=num>{tier}</td>"
        "<td class=num>{tier_level}</td>"
        "<td class=num>{eff}</td>"
        "<td class=num>{rate}</td>"
        "<td class=num>{ttc}</td>"
        "<td class=num>{cum}</td>"
        "<td>{status}</td>"
        "</tr>".format(
            cls="cleared" if step["cleared"] else "failed",
            tier=step["tier"],
            tier_level=step["tier_level"],
            eff=_num(step["effective_target"], 0),
            rate=_num(step["party_rate"]),
            ttc=_num(step["time_to_clear"], 1) if step["time_to_clear"] is not None else "&infin;",
            cum=_num(step["cumulative_time"], 1) if step["cumulative_time"] is not None else "&mdash;",
            status="cleared" if step["cleared"] else "ran out",
        )
        for step in trial["timeline"]
    )

    card_html = f"""
  <section class="card">
    <h2>{skill}</h2>
    <p class="meta">Party size {trial['party_size']} &middot;
       tier reached <strong>{trial['tier_reached']}</strong> &middot;
       {trial['points']} points</p>

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
            <th class="sort num" data-type="num">Rate @T{final_tier} <span class="arrow">&#8597;</span></th>
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
              <th>Result</th></tr>
        </thead>
        <tbody>{timeline_rows}</tbody>
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
  });
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


def _render_trials_html(week: dict) -> str:
    """Render the full trials page from a ``WeekResult`` dict."""
    strip = "".join(
        "<div class=\"stat\">"
        f"<div class=stat-skill>{html.escape(t['skill'])}</div>"
        f"<div class=stat-tier>Tier {t['tier_reached']}</div>"
        f"<div class=stat-pts>{t['points']} pts</div>"
        "</div>"
        for t in week["trials"]
    )

    cards_parts: list[str] = []
    assign_index: list[dict] = []
    for t_index, t in enumerate(week["trials"]):
        card_html, entries = _render_trial_card(t, t_index)
        cards_parts.append(card_html)
        assign_index.extend(entries)
    cards = "".join(cards_parts)

    bench = week["bench"]
    bench_html = (
        ", ".join(html.escape(n) for n in bench) if bench else "(none)"
    )
    # Bench members jump to the bench section (they have no roster row).
    assign_index.extend(
        {"n": n, "t": "Bench", "r": "bench-section"} for n in bench
    )

    # Embedded, self-contained assignment data for the player search. Escape
    # "<" so the JSON can never break out of the <script> element.
    assign_json = json.dumps(assign_index, ensure_ascii=False).replace(
        "<", "\\u003c"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SURVEY CORPS - Guild Trials</title>
<style>
  :root {{
    --bg: #0f1115; --panel: #171a21; --line: #2a2f3a;
    --text: #e6e8ec; --muted: #99a0ad; --accent: #6ea8fe;
    --on: #3ecf8e; --off: #3a3f4b; --warn: #e0b341;
  }}
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
  tr.failed td {{ color: var(--warn); }}
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
  footer {{ margin-top: 2rem; color: var(--muted); font-size: .8rem; }}
  footer ol {{ padding-left: 1.2rem; }}
  footer li {{ margin: .25rem 0; }}
  code {{ background: #0b0d11; padding: 0 .3em; border-radius: 3px; }}
</style>
</head>
<body>
<header>
  <h1>Guild Trials &mdash; Week of {html.escape(week['week_date'])}
      <span class="meta">({html.escape(_assignment_label(week))})</span></h1>
  <p class="meta">SURVEY CORPS &middot; {week['member_count']} members &middot;
     {html.escape(_assignment_detail(week))} &middot;
     generated {html.escape(week['generated_at'])} (UTC)</p>
  <p class="nav"><a href="index.html">&larr; Skill Register</a>
     &nbsp;&middot;&nbsp; <a href="signup.html">Sign-up Optimiser &rarr;</a></p>
</header>
<main>
  <div class="strip">
    {strip}
    <div class="total">
      <div class=stat-skill>Total</div>
      <div class=stat-tier>{week['total_points']}</div>
      <div class=stat-pts>guild points</div>
    </div>
  </div>

  <div class="search">
    <input id="member-search" type="search" autocomplete="off"
           placeholder="Search a member&hellip; (jump to their trial &amp; row)"
           aria-label="Search for a guild member">
    <div id="search-results" class="search-results" role="listbox" hidden></div>
  </div>
  {cards}

  <section class="card" id="bench-section">
    <h2>Bench</h2>
    <p class="meta">{len(bench)} member(s) not assigned to a trial this week
       (beyond {len(week['skills'])} &times; {week['cap']}).</p>
    <p>{bench_html}</p>
  </section>
</main>
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
        <code>0.05</code>. <em>BuildingSkillLevels = 0</em>: houses grant
        efficiency/speed, not skill levels. For Enhancing the <code>bonus</code>
        is the EnhancingSuccessRate (enhancer tool success; the Observatory's
        enhancing-success buff is 0 in the live data).</li>
    <li><strong>Points formula (ASSUMPTION).</strong>
        <code>points(T) = 100 + 100*T</code> for the highest tier T (0 if tier 1
        is not cleared). Fits the only observed data (milking tier1&rarr;200,
        tier2&rarr;300); the full schedule is unconfirmed.</li>
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
    <li><strong>Community buffs (event, WORKING ASSUMPTION).</strong> Three live
        community buffs are modelled, one per skill family. <em>Gathering</em>
        (Milking / Foraging / Woodcutting): a lab-style double-progress chance of
        <code>0.25</code> — the +20% community gathering buff plus ~5% carried on
        gear — scaling each member's rate by <code>(1 + doubleChance)</code>.
        <em>Production</em> (incl. Alchemy): +0.15 efficiency from the community
        production buff. <em>Enhancing</em>: +0.20 speed from the community
        enhancing buff. Placeholders that apply only while each buff is active;
        the ~5% gear term awaits the per-member gear harvest.</li>
    <li><strong>Houses (per-member, from the sheet).</strong> Each member's
        per-skill house level is read from the guild sheet's &ldquo;H&rdquo;
        column. Per the game data, gathering and production house rooms grant
        <code>+0.015</code> efficiency per level, while the enhancing house
        (Observatory) grants <code>+0.010</code> action-speed per level rather
        than efficiency. A blank H cell falls back to the assumed default of
        <code>level&nbsp;4</code>; levels are clamped to the in-game max of 8.</li>
    <li><strong>{html.escape(_assignment_footnote(week))}</strong></li>
  </ol>
  <p>Machine-readable copy of this page's data: <code>trials.json</code>.
     Static build from the public guild sheet; no credentials, read-only.</p>
</footer>
<script id="assign-data" type="application/json">{assign_json}</script>
<script>{_TRIALS_JS}</script>
</body>
</html>
"""


def _render_signup_html(p: dict) -> str:
    """Render the sign-up optimiser page from a ``signup.SignupPlan`` dict.

    The enforced plan (real sign-ups locked, open seats filled from the
    uncommitted pool) is shown per trial with volunteers colour-coded green and
    recommended fills blue; below it, the minimal strictly-improving swaps to
    reach the full-roster optimum, and the optimum itself for comparison.
    """
    optimal_by_skill = {o["skill"]: o for o in p["optimal_summary"]}

    # --- Summary strip: likely / with-swaps / ceiling ----------------------
    strip = f"""
    <div class="stat"><div class=stat-skill>Likely score</div>
      <div class=stat-tier>{p['enforced_total']}</div>
      <div class=stat-pts>sign-ups + recommended fills</div></div>
    <div class="stat"><div class=stat-skill>With swaps</div>
      <div class=stat-tier>{p['reachable_total']}</div>
      <div class=stat-pts>after the swaps below</div></div>
    <div class="total"><div class=stat-skill>Optimal ceiling</div>
      <div class=stat-tier>{p['optimal_total']}</div>
      <div class=stat-pts>best possible &middot; gap {p['gap']}</div></div>"""

    # --- Per-trial enforced rosters ----------------------------------------
    def _row(r: dict) -> str:
        assigned = r["status"] == "assigned"
        cls = "assigned" if assigned else "rec"
        badges = _badge(r["tool"], "Tool") + _badge(r["top"], "Top") + _badge(r["bot"], "Bot")
        if assigned:
            chip = '<span class="chip assigned">Signed up</span>'
        elif r.get("lifts_tier"):
            chip = f'<span class="chip rec">Fill +{r["fill_gain"]}</span>'
        else:
            chip = '<span class="chip filler">Fill (safe)</span>'
        level = "" if r["level"] is None else r["level"]
        return (
            f'<tr class="{cls}">'
            f'<th scope=row>{html.escape(r["name"])}</th>'
            f'<td class=num>{level}</td>'
            f'<td class=cbadges>{badges}</td>'
            f'<td class=num>{_num(r["rate_final"])}</td>'
            f'<td>{chip}</td>'
            "</tr>"
        )

    cards = []
    for t in p["trials"]:
        opt = optimal_by_skill.get(t["skill"], {})
        opt_tier = opt.get("tier_reached")
        opt_note = ""
        if opt_tier is not None and opt_tier != t["tier_reached"]:
            opt_note = (
                f' &middot; <span class="hl">optimal reaches tier {opt_tier} '
                f'({opt.get("points")} pts)</span>'
            )
        n_assigned = sum(1 for r in t["roster"] if r["status"] == "assigned")
        n_rec = sum(1 for r in t["roster"] if r["status"] == "recommended")
        rows = "".join(_row(r) for r in t["roster"])
        cards.append(f"""
  <section class="card">
    <h2>{html.escape(t['skill'])}</h2>
    <p class="meta">Party {t['party_size']} &middot; tier <strong>{t['tier_reached']}</strong>
       &middot; {t['points']} pts &middot; {n_assigned} signed up, {n_rec} recommended,
       {t['open_seats']} seat(s) still open{opt_note}</p>
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
    if p["swaps"]:
        swap_rows = "".join(
            f'<tr><td><span class="chip swap">{html.escape(s["action"])}</span></td>'
            f'<td>{html.escape(s["note"])}</td>'
            f'<td class=num>+{s["gain"]}</td></tr>'
            for s in p["swaps"]
        )
        gained = sum(s["gain"] for s in p["swaps"])
        if p["reachable_total"] >= p["optimal_total"]:
            swap_lead = (
                f"These {len(p['swaps'])} swap(s) raise the likely "
                f"{p['enforced_total']} to {p['reachable_total']} points "
                "&mdash; the optimal ceiling. Each is purely advisory and "
                "overrides a sign-up."
            )
        else:
            swap_lead = (
                f"These {len(p['swaps'])} swap(s) raise the likely "
                f"{p['enforced_total']} to {p['reachable_total']} points "
                f"(+{gained}); a further {p['optimal_total'] - p['reachable_total']} "
                "would need a wider reshuffle. Each is advisory and overrides a "
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
    </div>
  </section>"""
    else:
        swaps_section = f"""
  <section class="card">
    <h2>Recommended swaps to reach optimal</h2>
    <p class="meta">None &mdash; the enforced sign-up plan ({p['enforced_total']} pts)
       already matches the optimal ceiling ({p['optimal_total']} pts). Nothing to change.</p>
  </section>"""

    # --- Optimal comparison table ------------------------------------------
    opt_rows = "".join(
        f'<tr><th scope=row>{html.escape(o["skill"])}</th>'
        f'<td class=num>{o["party_size"]}</td>'
        f'<td class=num>{o["tier_reached"]}</td>'
        f'<td class=num>{o["points"]}</td></tr>'
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

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SURVEY CORPS - Sign-up Optimiser</title>
<style>
  :root {{
    --bg: #0f1115; --panel: #171a21; --line: #2a2f3a;
    --text: #e6e8ec; --muted: #99a0ad; --accent: #6ea8fe;
    --on: #3ecf8e; --off: #3a3f4b; --warn: #e0b341;
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
  .chip.swap {{ background: rgba(224,179,65,.20); color: var(--warn);
               text-transform: capitalize; }}
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
  <p class="meta">SURVEY CORPS &middot; {p['roster_count']} members &middot;
     {p['signup_count']} signed up &middot; generated {html.escape(p['generated_at'])} (UTC)</p>
  <p class="nav"><a href="index.html">&larr; Skill Register</a>
     &nbsp;&middot;&nbsp; <a href="trials.html">Guild Trials (full optimum) &rarr;</a></p>
</header>
<main>
  <div class="strip">{strip}</div>
  <p class="legend">
    <span><span class="sw" style="background:var(--assigned)"></span> Signed up (locked)</span>
    <span><span class="sw" style="background:var(--rec)"></span> Recommended fill (from the uncommitted pool)</span>
    <span><span class="sw" style="background:var(--warn)"></span> Swap (advisory)</span>
  </p>
  {cards_html}
  {swaps_section}

  <section class="card">
    <h2>Optimal (unconstrained) for comparison</h2>
    <p class="meta">The best possible teams over the full {p['roster_count']}-member roster,
       ignoring who signed up &mdash; the ceiling above. Full rosters on the
       <a href="trials.html">Guild Trials</a> page.</p>
    <div class="scroll">
      <table>
        <thead><tr><th>Trial</th><th class=num>Party</th>
          <th class=num>Tier</th><th class=num>Points</th></tr></thead>
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
        the sheet's <em>Trial Signup</em> tab is locked into that trial and shown
        <span style="color:var(--on)">green</span>; they are never moved or benched
        in the plan.</li>
    <li><strong>Open seats are recommended fills.</strong> Remaining seats (up to the
        {p['cap']}-per-party cap) are offered to members who signed up for nothing
        &mdash; the {len(p['non_signups'])} uncommitted members &mdash; shown
        <span style="color:var(--accent)">blue</span>. A fill is only suggested where
        it does not <em>lower</em> a party's tier; ones that raise it are marked
        <code>Fill +pts</code>, harmless riders <code>Fill (safe)</code>.
        Uncommitted members with no useful seat: {bench_html}.</li>
    <li><strong>Swaps are advisory.</strong> The swap list is the minimal set of
        strictly-improving moves (each raising the score) from the enforced plan
        toward the full-roster optimum. Applying them overrides sign-ups.</li>
    <li><strong>Optimal is the ceiling.</strong> The optimum reuses the exact
        assignment the <a href="trials.html">Guild Trials</a> page computes, so the
        two never disagree. The scoring model, tiers and equipment assumptions are
        documented there.</li>
  </ol>
  <p>Machine-readable copy of this page's data: <code>signup.json</code>.
     Static build from the public guild sheet; no credentials, read-only.</p>
</footer>
</body>
</html>
"""


def main() -> int:
    try:
        csv_text = fetch_csv()
        members = parse(csv_text)
    except SheetStructureError as exc:
        print(f"ERROR: sheet structure mismatch:\n{exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    data = process(members)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "data.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUTPUT_DIR / "index.html").write_text(_render_html(data), encoding="utf-8")

    # --- Guild Trials (Phase 1) ---------------------------------------------
    # Fetch SC member data LIVE via the named-tab scraper and simulate this
    # week's four skilling trials, then emit trials.html + trials.json.
    try:
        sc = scrape_member_tab(config.TABS["sc"])
    except SheetStructureError as exc:
        print(f"ERROR: sheet structure mismatch (trials):\n{exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    week = trials_model.run_week(sc.members)
    week_dict = week.to_dict()
    (OUTPUT_DIR / "trials.json").write_text(
        json.dumps(week_dict, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUTPUT_DIR / "trials.html").write_text(
        _render_trials_html(week_dict), encoding="utf-8"
    )

    # --- Sign-up Optimiser ---------------------------------------------------
    # Fetch the real "Trial Signup" tab, enforce those picks, recommend fills
    # for the open seats, and diff against the (already-computed) optimum. Reuses
    # ``week`` as the optimal ceiling so the two pages never disagree.
    try:
        picks = signup_model.parse_signup(signup_model.fetch_signup_csv())
    except SheetStructureError as exc:
        print(f"ERROR: sheet structure mismatch (signup):\n{exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    optimal_total, optimal_summary = signup_model.optimal_from_week(week)
    plan = signup_model.plan(sc.members, picks, optimal_total, optimal_summary)
    plan_dict = plan.to_dict()
    (OUTPUT_DIR / "signup.json").write_text(
        json.dumps(plan_dict, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUTPUT_DIR / "signup.html").write_text(
        _render_signup_html(plan_dict), encoding="utf-8"
    )

    print(
        f"Built _site/ with {data['member_count']} members "
        f"({len(data['skills'])} skills); trials: "
        + ", ".join(
            f"{t.skill} T{t.tier_reached}/{t.points}pts" for t in week.trials
        )
        + f" (total {week.total_points} pts); signup: "
        + f"{plan.signup_count} signed, enforced {plan.enforced_total} pts "
        + f"-> {plan.reachable_total} via {len(plan.swaps)} swap(s) "
        + f"(optimal {plan.optimal_total})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
