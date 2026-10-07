"""Read one guild's COMBAT building value from its machine-owned tab.

The combat optimiser in ~/pie/SCLIRoster simulates both combat teams against every
combat boss with each combat guild building at its level and at +1, and posts one
row per building (``optimizer/src/publish/buildingTab.js``) through the Apps Script
endpoint in ``apps-script/`` to ``config.BUILDING_VALUE_TABS``:

    Upgrade | Hrid | Level | Next Level | GP Cost | Gain GP Per Run | ... |
    Payback Weeks | ... | Verdict | Rank | Recommendation | ... | Generated At

``build.py`` publishes what this module returns as ``buildings.json``, next to the
skilling building and shrine probes, so a page can rank every upgrade on one scale.

THE UNITS (the writer's banner has the long form). Every Guild Point figure is BASE
trial points, the same basis as ``trials.upgrade_payback_*``. ``Payback Weeks`` is
``cost / (gain per team run * team runs per week)`` and is the figure to put beside a
skilling row's ``weeks_to_return``.

Same three outcomes as ``combat.parse_combat``: an empty or header-only tab is
``observed=False`` (the tab is created empty and may not have been written yet); a
wrong tab, a changed header, or another guild's id raise ``SheetStructureError``,
which ``build`` degrades on and never lets stop the deploy.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Optional

from . import config
from .combat import fetch_combat_csv
from .reader import SheetStructureError, _cell, _to_int

HRID_PREFIX = "/guild_buildings/"

# header name -> output key, and how to read the cell
_INT = "int"
_FLOAT = "float"
_TEXT = "text"
_COLUMNS = {
    "Upgrade": ("name", _TEXT),
    "Hrid": ("hrid", _TEXT),
    "Level": ("level", _INT),
    "Next Level": ("next_level", _INT),
    "GP Cost": ("cost", _FLOAT),
    "Gain GP Per Run": ("gain_gp_per_run", _FLOAT),
    "Gain GP Lo": ("gain_gp_lo", _FLOAT),
    "Gain GP Hi": ("gain_gp_hi", _FLOAT),
    "Gain Pct": ("gain_pct", _FLOAT),
    "Gain Pct Lo": ("gain_pct_lo", _FLOAT),
    "Gain Pct Hi": ("gain_pct_hi", _FLOAT),
    "Runs Per Week": ("runs_per_week", _INT),
    "Gain GP Per Week": ("gain_gp_per_week", _FLOAT),
    "Payback Runs": ("payback_runs", _FLOAT),
    "Payback Weeks": ("payback_weeks", _FLOAT),
    "GP Per Percent": ("gp_per_percent", _FLOAT),
    "Verdict": ("verdict", _TEXT),
    "Rank": ("rank", _INT),
    "Recommendation": ("recommendation", _TEXT),
    "Seeds": ("seeds", _INT),
}
assert set(_COLUMNS) | {"Guild Id", "Cycle", "Generated At"} == set(
    config.BUILDING_VALUE_HEADERS
), "building_value._COLUMNS has drifted from config.BUILDING_VALUE_HEADERS"


@dataclass
class GuildBuildingValue:
    tab: str
    guild_key: str
    observed: bool
    generated_at: str = ""
    cycle: str = ""
    rows: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tab": self.tab,
            "observed": self.observed,
            "generated_at": self.generated_at,
            "cycle": self.cycle,
            "gp_basis": "base",
            "rows": self.rows,
        }


def _to_float(raw: str) -> Optional[float]:
    """A gviz numeric cell; blank -> None. Tolerates a thousands separator."""
    raw = raw.strip().replace(",", "")
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _read(raw: str, kind: str):
    if kind == _TEXT:
        return raw or None
    if kind == _INT:
        f = _to_float(raw)
        return None if f is None else int(round(f))
    return _to_float(raw)


def parse_building_value(
    csv_text: str, guild_key: str, tab: str = ""
) -> GuildBuildingValue:
    """Parse a Building Value tab's gviz CSV. See the module docstring."""
    tab = tab or config.BUILDING_VALUE_TABS.get(guild_key, "")
    unobserved = GuildBuildingValue(tab=tab, guild_key=guild_key, observed=False)
    if csv_text.strip() == "":
        return unobserved
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        return unobserved

    header = [c.strip() for c in rows[0]]
    expected = list(config.BUILDING_VALUE_HEADERS)
    if header[: len(expected)] != expected or any(h for h in header[len(expected):]):
        raise SheetStructureError(
            f"the {tab!r} tab's header is not the building-value header "
            f"({expected[0]!r}, {expected[1]!r}, ...): got {header[:4]!r}. Either gviz "
            f"served another tab (it does that for a name it cannot find — create the "
            f"tab), or SCLIRoster's buildingTab.js HEADER changed without "
            f"config.BUILDING_VALUE_HEADERS."
        )
    col = {name: i for i, name in enumerate(expected)}

    data = [r for r in rows[1:] if any(cell.strip() for cell in r)]
    if not data:
        return unobserved

    want_id = config.GUILD_IDS.get(guild_key)
    out: list[dict] = []
    stamps: list[str] = []
    cycles: list[str] = []
    for offset, raw in enumerate(data):
        row_no = offset + 2
        gid = _cell(raw, col["Guild Id"])
        if want_id is not None and gid != "" and _to_int(gid) != want_id:
            raise SheetStructureError(
                f"the {tab!r} tab carries guild id {gid!r} on row {row_no}, but "
                f"{guild_key!r} is guild id {want_id}: another guild's building value. "
                f"Check TAB_BY_GUILD in SCLIRoster's optimizer/src/publish/buildingTab.js."
            )
        hrid = _cell(raw, col["Hrid"])
        if not hrid.startswith(HRID_PREFIX):
            raise SheetStructureError(
                f"the {tab!r} tab carries Hrid {hrid!r} on row {row_no}, which is not "
                f"a guild building ({HRID_PREFIX!r}). This tab is machine-written; "
                f"re-run the optimiser's publish rather than editing it."
            )
        rec = {key: _read(_cell(raw, col[name]), kind)
               for name, (key, kind) in _COLUMNS.items()}
        rec["kind"] = "combat"
        out.append(rec)
        if _cell(raw, col["Generated At"]):
            stamps.append(_cell(raw, col["Generated At"]))
        if _cell(raw, col["Cycle"]):
            cycles.append(_cell(raw, col["Cycle"]))

    # Rank order, unranked last, as the writer ranked them.
    out.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["hrid"]))
    return GuildBuildingValue(
        tab=tab,
        guild_key=guild_key,
        observed=True,
        generated_at=min(stamps) if stamps else "",
        cycle=cycles[0] if cycles else "",
        rows=out,
    )


def scrape_building_value_tab(tab_name: str, guild_key: str) -> GuildBuildingValue:
    """Fetch and parse one guild's Building Value tab.

    Raises ``SheetStructureError`` on a structural problem (degraded by build) and
    ``RuntimeError`` on a network failure (fatal, as for every tab on this host).
    """
    return parse_building_value(fetch_combat_csv(tab_name), guild_key, tab=tab_name)
