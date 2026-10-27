"""Read members' uploaded profiles: the highest-ranked per-field source.

The private ``SC Profiles`` / ``LI Profiles`` tabs, written by SCLIRoster's
userscript and readable only through SCLIRoster's owner-only read endpoint
(``SCLIRoster/apps-script/read/Code.gs``). This is the ONE module in guild that
holds a credential; every other reader is anonymous gviz.

Mirrors ``SCLIRoster/optimizer/src/sources/privateProfiles.js``:

- the first 17 header columns are FROZEN; a shifted header is refused, never
  reinterpreted;
- a response that is HTML, not JSON, ``ok: false`` or ``truncated`` is never
  parsed as data;
- ``equipped`` is never read: ``items`` is what a member OWNS, and the planner
  assumes the best owned tool, as combat does;
- the token and the URL never appear in a message (``_redact``).

Raw profile data never leaves this process. Only derived planner fields (a level,
a house level, a tool name + enhancement, gear levels) reach the merge, and only
those fields' outputs reach ``_site/``.

:func:`load` never raises: any failure returns ``(None, reason)`` and the build
carries on exactly as it did before this source existed (roster, then manual).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config, identity
from . import gear as gear_model

URL_ENV = "PROFILES_URL"
TOKEN_ENV = "PROFILES_READ_TOKEN"
LOCAL_CREDENTIALS = Path.home() / ".config" / "scliroster" / "credentials.json"

# Mirrors PROFILE_HEADER in privateProfiles.js. The first REQUIRED_COLUMNS are
# frozen; anything after them is tail growth and is not read here.
PROFILE_HEADER = (
    "characterId", "name", "guildId", "capturedAt", "itemCount",
    "skills", "abilities", "equipped", "items",
    "tier_beginner", "tier_novice", "tier_adept",
    "tier_veteran", "tier_elite", "tier_champion",
    "houses", "shrines",
)
REQUIRED_COLUMNS = 17
_COL = {name: i for i, name in enumerate(PROFILE_HEADER)}

# Tool display name (config.TOOL_STATS key) by item hrid: "Rainbow Chisel" ->
# "/items/rainbow_chisel".
TOOL_BY_HRID = {
    "/items/" + name.lower().replace(" ", "_"): name for name in config.TOOL_STATS
}


class ProfileError(Exception):
    """A read or parse refusal. Its message never carries a secret."""


@dataclass
class ProfileRow:
    """One member's derived planner fields, keyed by ``config.SKILLS`` name.

    A skill absent from a mapping means the profile did not say.
    """

    character_id: int
    captured_at: str = ""
    levels: dict[str, int] = field(default_factory=dict)
    houses: dict[str, int] = field(default_factory=dict)
    # skill -> (TOOL_STATS name, enhancement): the best OWNED tool by modelled value.
    tools: dict[str, tuple[str, int]] = field(default_factory=dict)
    # Owned items gear.GEAR_STATS models, {hrid: enhancement}. None = not stated.
    gear: Optional[dict[str, int]] = None


def tool_value(item: Optional[str], enhance: Optional[int]) -> Optional[float]:
    """The modelled bonus of a named tool, ``trials.tool_bonus``'s arithmetic
    through the shared ``gear.effective_stat``. None for an unmodelled item."""
    stats = config.TOOL_STATS.get(item) if item else None
    if stats is None:
        return None
    _skill, _channel, base, per = stats
    level = config.TOOL_ENHANCE_WHEN_UNKNOWN if enhance is None else enhance
    return gear_model.effective_stat(base, per, level)


# ---------------------------------------------------------------------------
# Credentials and the read
# ---------------------------------------------------------------------------
def load_credentials() -> Optional[tuple[str, str]]:
    """``(url, token)`` from the environment, else the local SCLIRoster file."""
    url, token = os.environ.get(URL_ENV, ""), os.environ.get(TOKEN_ENV, "")
    if url and token:
        return url, token
    try:
        data = json.loads(LOCAL_CREDENTIALS.read_text())
        url, token = data.get("profilesUrl") or "", data.get("readToken") or ""
    except (OSError, ValueError, AttributeError):
        return None
    return (url, token) if url and token else None


def _redact(text: str, *secrets: str) -> str:
    """credentials.js ``redact``: every secret, raw and url-encoded, removed."""
    for s in secrets:
        if not isinstance(s, str) or len(s) < 4:
            continue
        for form in {s, urllib.parse.quote(s, safe=""), urllib.parse.quote_plus(s)}:
            text = text.replace(form, "«redacted»")
    return text


def accept_response(raw: str, where: str) -> dict:
    """The C9 contract: HTML, non-JSON, ok:false and truncated are refused."""
    head = raw[:512].lower().lstrip()
    if head.startswith("<!doctype") or head.startswith("<html"):
        raise ProfileError(
            f"{where} answered HTML, not JSON (a Google sign-in or error page); "
            "never parsed as data."
        )
    try:
        body = json.loads(raw)
    except ValueError:
        raise ProfileError(f"{where} answered something that is not JSON") from None
    if not isinstance(body, dict) or body.get("ok") is not True:
        err = body.get("error") if isinstance(body, dict) else None
        raise ProfileError(f"{where} reports ok:false — {err or 'no error given'}")
    if body.get("truncated"):
        raise ProfileError(
            f"{where} is a TRUNCATED read ({body.get('rowCount')} of more than "
            f"{body.get('maxRows')} rows); half a roster is not used."
        )
    return body


def fetch(tab: str, url: str, token: str, attempts: int = 3) -> dict:
    """GET the tab through the read endpoint. Every message is redacted.

    Retries everything, because a GET has no effect to take and the common HTML
    answer is a cold googleusercontent hop rather than a permanent refusal.
    """
    where = f"profiles endpoint (tab {tab!r})"
    full = f"{url}?" + urllib.parse.urlencode({"tab": tab, "token": token})
    last = ""
    for attempt in range(attempts):
        if attempt:
            time.sleep(attempt)
        try:
            req = urllib.request.Request(full, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as res:
                return accept_response(res.read().decode("utf-8", "replace"), where)
        except ProfileError as exc:
            last = str(exc)
            if "ok:false" in last or "TRUNCATED" in last:
                break  # the endpoint's own deliberate answer; asking again is moot
        except urllib.error.HTTPError as exc:
            last = f"{where} answered HTTP {exc.code}"
            if exc.code != 429 and exc.code < 500:
                break  # 401/403/404 answer the same every time
        except Exception as exc:  # noqa: BLE001 - urllib raises a zoo
            # The type only: a transport message can quote the (redirect) URL.
            last = f"{where} could not be read ({type(exc).__name__})"
    raise ProfileError(_redact(last, token, url))


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------
def assert_header(header) -> None:
    if not isinstance(header, list) or len(header) < REQUIRED_COLUMNS:
        raise ProfileError("profiles header is missing or too short")
    for i in range(REQUIRED_COLUMNS):
        got = str(header[i] if header[i] is not None else "").strip()
        if got != PROFILE_HEADER[i]:
            raise ProfileError(
                f"profiles header SHIFTED at column {i + 1}: expected "
                f"{PROFILE_HEADER[i]!r}, found {got!r}; refused."
            )


def parse_pairs(cell) -> Optional[dict[str, int]]:
    """``"milking:105;/skills/foraging:90"`` -> ``{"milking": 105, "foraging": 90}``.

    Absent -> None ("we do not know"); blank -> {} ("owns none"). The slug keeps
    only its last path segment. A malformed pair is skipped.
    """
    if cell is None:
        return None
    out: dict[str, int] = {}
    for piece in str(cell).split(";"):
        slug, sep, raw = piece.strip().rpartition(":")
        if not sep or not slug:
            continue
        try:
            value = int(float(raw))
        except (ValueError, OverflowError):
            continue
        out[slug.rsplit("/", 1)[-1]] = value
    return out


def _cell(row: list, name: str):
    i = _COL[name]
    return row[i] if i < len(row) else None


def parse_row(row: list) -> Optional[ProfileRow]:
    cid = identity.parse_id(_cell(row, "characterId"))
    if cid is None:
        return None
    levels = parse_pairs(_cell(row, "skills")) or {}
    houses = parse_pairs(_cell(row, "houses")) or {}
    items = parse_pairs(_cell(row, "items"))
    prof = ProfileRow(character_id=cid, captured_at=str(_cell(row, "capturedAt") or ""))

    for skill in config.SKILLS:
        level_slug, house_col, _tool_col = config.ROSTER_COLUMNS[skill]
        if level_slug in levels:
            prof.levels[skill] = levels[level_slug]
        house_slug = house_col.removeprefix("house_")
        if house_slug in houses:
            prof.houses[skill] = houses[house_slug]

    if items is not None:
        best: dict[str, tuple[float, str, int]] = {}
        for slug, enh in items.items():
            name = TOOL_BY_HRID.get("/items/" + slug)
            if name is None:
                continue
            skill = config.TOOL_STATS[name][0]
            value = tool_value(name, enh)
            if skill not in best or (value, name) > best[skill][:2]:
                best[skill] = (value, name, enh)
        prof.tools = {s: (name, enh) for s, (_v, name, enh) in best.items()}
        prof.gear = {
            "/items/" + slug: enh
            for slug, enh in items.items()
            if "/items/" + slug in gear_model.GEAR_STATS
        }
    return prof


def parse(body: dict) -> dict[int, ProfileRow]:
    """``{characterId: ProfileRow}``; a duplicated id keeps the newest capture."""
    assert_header(body.get("header"))
    out: dict[int, ProfileRow] = {}
    for row in body.get("rows") or []:
        if not isinstance(row, list):
            continue
        prof = parse_row(row)
        if prof is None:
            continue
        old = out.get(prof.character_id)
        if old is None or prof.captured_at > old.captured_at:
            out[prof.character_id] = prof
    return out


def load(tab: str) -> tuple[Optional[dict[int, ProfileRow]], str]:
    """``(profiles, note)``. Never raises; profiles is None when unusable."""
    if not config.PROFILES_SOURCE_ENABLED:
        return None, "config.PROFILES_SOURCE_ENABLED is off"
    creds = load_credentials()
    if creds is None:
        return None, f"no credentials ({URL_ENV} / {TOKEN_ENV} unset)"
    url, token = creds
    try:
        profiles = parse(fetch(tab, url, token))
    except Exception as exc:  # noqa: BLE001 - this source must never stop a build
        return None, _redact(f"{tab!r} unreadable: {exc}", token, url)
    return profiles, f"{len(profiles)} profiles read from {tab!r}"
