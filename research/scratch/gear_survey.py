"""Measure the `gearSeen` union on both guilds. The evidence for research/per-item-gear.md.

Not imported by the build. Run:  .venv/bin/python research/scratch/gear_survey.py
Every table in research/per-item-gear.md is a section of this script's output, so a
re-run is how that document is checked rather than trusted.
"""
from __future__ import annotations

import collections
import csv
import io
import json
import re
import statistics as st

from src import config
from src.reader import norm_name
from src.scraper import fetch_tab_csv, scrape_member_tab

CAT = json.load(open("research/item-stats.json"))["items"]
MULT = config.ENHANCEMENT_MULT_TABLE
# The four channels a RATE model may read. Experience, RareFind, EssenceFind,
# taskSpeed and drinkConcentration buff loot, XP or the task board and must never
# enter a race — the same rule guild_shrine_bonuses applies to Rarity/Spirit/Scholar.
RACE_STAT = re.compile(r"(Speed|Efficiency|enhancingSuccess|gatheringQuantity)$")

NAME_BY_HRID = {h: v["name"] for h, v in CAT.items()}
HRID_BY_NAME = {v["name"]: h for h, v in CAT.items()}


def race_stats(hrid: str) -> dict[str, float]:
    stats = CAT.get(hrid, {}).get("noncombatStats") or {}
    return {k: v for k, v in stats.items() if RACE_STAT.search(k)}


def slot(hrid: str) -> str:
    return CAT.get(hrid, {}).get("slot") or ""


RACE_ITEMS = {h for h in CAT if race_stats(h)}
TOOLS = {h for h in RACE_ITEMS if slot(h).endswith("_tool")}
NONTOOL = RACE_ITEMS - TOOLS
CAPES = {h for h in RACE_ITEMS if slot(h) == "back"}
GARMENTS = {h for h in RACE_ITEMS if slot(h) in ("body", "legs")}
FAMILY = {
    "/items/collectors_boots",
    "/items/red_culinary_hat",
    "/items/eye_watch",
    "/items/enchanted_gloves",
}
ACCESSORY_SLOTS = ("neck", "ring", "earrings")


def effective(hrid: str, level: int) -> float:
    """base + ENHANCEMENT_MULT_TABLE[level] * per, on the item's first race stat."""
    base = list(race_stats(hrid).values())[0]
    per = list(CAT[hrid]["noncombatEnhancementBonuses"].values())[0]
    return base + MULT[level] * per


def read_guild(guild: str):
    """(visible, hidden, blank) where visible is [(name, {hrid: level})]."""
    rows = list(csv.reader(io.StringIO(fetch_tab_csv(config.ROSTER_TABS[guild]))))
    hdr = [c.strip() for c in rows[0]]
    gi, ni = hdr.index("gearSeen"), hdr.index("name")
    visible, hidden, blank = [], [], []
    for r in rows[1:]:
        if not r or not r[ni].strip():
            break
        name = r[ni].strip()
        cell = r[gi].strip() if gi < len(r) else ""
        if cell == "":
            blank.append(name)
            continue
        items = json.loads(cell)["items"]
        if not items:
            hidden.append(name)
            continue
        visible.append((name, {i["hrid"]: i.get("level") for i in items}))
    return visible, hidden, blank


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    guilds = {g: read_guild(g) for g in config.ROSTER_TABS}

    section("1. Coverage")
    for g, (vis, hid, blank) in guilds.items():
        print(f"  {g.upper():3s} visible={len(vis):4d} gear-hidden={len(hid):3d} "
              f"blank-cell={len(blank):3d}")

    section("2. Per-item ownership and enhancement, pooled over both guilds")
    pooled = collections.defaultdict(list)
    total = sum(len(v) for v, _, _ in guilds.values())
    for vis, _, _ in guilds.values():
        for _, owned in vis:
            for h, l in owned.items():
                if h in NONTOOL:
                    pooled[h].append(l)
    hdr = f"  {'item':26s} {'slot':10s} {'n':>4s} {'own%':>5s} {'mean':>5s} {'mode':>4s}  channels"
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    for h in sorted(pooled, key=lambda x: (slot(x), -len(pooled[x]))):
        L = [x for x in pooled[h] if isinstance(x, int)]
        mode = collections.Counter(L).most_common(1)[0][0] if L else 0
        print(f"  {NAME_BY_HRID[h]:26s} {slot(h):10s} {len(pooled[h]):4d} "
              f"{len(pooled[h]) / total:5.0%} {st.mean(L) if L else 0:5.2f} {mode:4d}  "
              f"{','.join(sorted(race_stats(h)))}")

    section("3. Slot multiplicity — does the union hold two items in one slot?")
    multi = collections.Counter()
    for vis, _, _ in guilds.values():
        for _, owned in vis:
            byslot = collections.Counter(slot(h) for h in owned if h in NONTOOL)
            for s in set(slot(h) for h in NONTOOL):
                multi[(s, byslot.get(s, 0))] += 1
    for s in sorted({s for s, _ in multi}):
        d = {k: v for (ss, k), v in multi.items() if ss == s}
        print(f"  {s:10s} " + "  ".join(f"{k} item(s):{d[k]:4d}" for k in sorted(d)))

    section("4. The four family pieces are held all-or-nothing")
    joint = collections.Counter()
    for vis, _, _ in guilds.values():
        for _, owned in vis:
            joint[len(FAMILY & set(owned))] += 1
    for k in sorted(joint):
        print(f"  {k} of the four: {joint[k]:4d}  ({joint[k] / total:4.0%})")

    section("5. Manual top/bot checkbox against the gear union")
    for g in guilds:
        vis, _, _ = guilds[g]
        seen_by = {norm_name(n): set(o) for n, o in vis}
        tab = collections.Counter()
        for m in scrape_member_tab(config.TABS[g]).members:
            owned = seen_by.get(norm_name(m.name))
            if owned is None:
                continue
            for skill, entry in m.skills.items():
                for kind, flag in (("body", entry.top), ("legs", entry.bot)):
                    h = garment_for(skill, kind)
                    tab[(kind, bool(flag), bool(h and h in owned))] += 1
        print(f"  {g.upper()}: " + "  ".join(
            f"{k}/tick={t}/seen={s}:{v}" for (k, t, s), v in sorted(tab.items()) if v))

    section("6. The tool columns against the gear union")
    agree = collections.Counter()
    for g in guilds:
        rows = list(csv.reader(io.StringIO(fetch_tab_csv(config.ROSTER_TABS[g]))))
        hdr = [c.strip() for c in rows[0]]
        gi, ni = hdr.index("gearSeen"), hdr.index("name")
        for r in rows[1:]:
            if not r or not r[ni].strip():
                break
            cell = r[gi].strip() if gi < len(r) else ""
            if not cell:
                continue
            owned = {i["hrid"]: i.get("level") for i in json.loads(cell)["items"]}
            if not owned:
                continue
            for skill, (_, _, tcol) in config.ROSTER_COLUMNS.items():
                name = r[hdr.index(tcol)].strip()
                enh = r[hdr.index(tcol + config.ROSTER_TOOL_ENH_SUFFIX)].strip()
                if not name:
                    agree["column blank"] += 1
                    continue
                h = HRID_BY_NAME.get(name)
                if h not in owned:
                    agree["column names a tool the union never saw"] += 1
                elif enh == "":
                    agree["column enhancement blank, union has a level"] += 1
                elif int(enh) == owned[h]:
                    agree["agree exactly"] += 1
                else:
                    agree["LEVEL MISMATCH"] += 1
    print("  " + json.dumps(dict(agree), indent=2).replace("\n", "\n  "))

    section("7. The three imputation statistics, per guild")
    for g, (vis, _, _) in guilds.items():
        lv = collections.defaultdict(list)
        for _, owned in vis:
            for h, l in owned.items():
                if h in RACE_ITEMS and isinstance(l, int):
                    lv[h].append(l)
        capes = [effective(h, l) for h in CAPES for l in lv.get(h, [])]
        garments = [l for h in GARMENTS for l in lv.get(h, [])]
        print(f"  {g.upper()}")
        print(f"    cape pooled mean EFFECTIVE speed  n={len(capes):3d} "
              f"{st.mean(capes):.6f}")
        for h in sorted(FAMILY, key=lambda x: NAME_BY_HRID[x]):
            L = lv.get(h, [])
            print(f"    {NAME_BY_HRID[h]:22s} mean LEVEL   n={len(L):3d} "
                  f"{st.mean(L) if L else 0:.6f}")
        print(f"    garment pooled mean LEVEL         n={len(garments):3d} "
              f"{st.mean(garments) if garments else 0:.6f}")


def garment_for(skill: str, slot_name: str) -> str | None:
    """The body/legs garment covering ``skill``, by the catalogue's own channel."""
    key = _SKILL_STAT[skill]
    for h in GARMENTS:
        if slot(h) != slot_name:
            continue
        stats = race_stats(h)
        if f"{key}Efficiency" in stats or f"{key}Speed" in stats:
            return h
    return None


_SKILL_STAT = {
    "Milking": "milking", "Foraging": "foraging", "Woodcutting": "woodcutting",
    "C.Smithing": "cheesesmithing", "Crafting": "crafting", "Tailoring": "tailoring",
    "Cooking": "cooking", "Brewing": "brewing", "Bell Farming": "alchemy",
    "Enhancing": "enhancing",
}

if __name__ == "__main__":
    main()
