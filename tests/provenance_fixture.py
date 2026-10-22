"""The provenance block _write_guild attaches to every page dict, roster OFF.

Production always attaches provenance before rendering (build._write_guild), so the
renderers read it unconditionally. Tests that render a bare run_week()/plan dict
attach this manual-tab answer first, exactly as _write_guild would with
config.ROSTER_SOURCE_ENABLED off.
"""


def manual_provenance(member_count: int) -> dict:
    """The manual-tab provenance for ``member_count`` members."""
    return {
        "enabled": False, "source": "manual tab", "roster_backed": 0,
        "manual_backed": member_count, "admitted": 0, "admitted_names": [],
        "reported_not_seated": [], "captured_at": "", "age_days": None,
        "stale": False, "gear_hidden": 0, "unknown_tools": 0,
        "unknown_tool_items": {}, "blank_enhancements": 0,
        "unmatched_roster": [], "unmatched_members": [], "normalized_matches": [],
        "ambiguous": [], "refused": "", "unavailable": "",
    }


def with_provenance(page: dict, count_key: str) -> dict:
    page.setdefault("provenance", manual_provenance(page[count_key]))
    return page
