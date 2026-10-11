import pytest

from src import identity


@pytest.fixture(autouse=True)
def _no_name_history_fetch(monkeypatch):
    """No test may reach Google for the Name History tab: header-only = observed,
    empty, silent. A test that wants history monkeypatches this again."""
    monkeypatch.setattr(
        identity,
        "fetch_name_history_csv",
        lambda tab: "Character Id,Name,Guild Id,First Seen,Last Seen\n",
    )
