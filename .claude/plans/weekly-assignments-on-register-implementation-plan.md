# Implementation plan — this week's assignments on the register (`data.json` + `index.html`)

**ResearchPack:** none — no external library is involved. The research is the codebase,
and every API this plan names is cited `file:line` against the working tree at
`842faeb` (`src/build.py`, `src/trials.py`, `src/reader.py`, `src/roster.py` unmodified
there; `src/config.py` carries unrelated uncommitted edits — see step 1). **Baseline:**
`.venv/bin/python -m pytest tests/ -q` → 429 passed in 7m27s. **Precedent:** the shape
of `.claude/plans/per-item-gear-implementation-plan.md` — one design decision argued,
everything else additive, one config line to roll back.

---

## 1. What changes, in one paragraph

The register is published as `_site/index.html` and `_site/data.json`; the optimiser's
week is published as `trials.html` / `trials.json` (`build.py:49-50`). A reader who
wants "what is this member doing this week" today fetches the second file and walks
four rosters of ~28 entries; the in-game Tampermonkey fetch that motivates this has one
request to spend. After this change `data.json` **also** carries a compact projection
of the week — a top-level `week` block (parties as name lists, bench, draw, staleness)
and a per-member `trial` stamp — and `index.html` shows a "This week's trials" section
and a `Trial` column. `trials.json` is byte-for-byte what it is today and remains the
full record. Both guilds get it (`_site/` and `_site/li/`), and
`config.REGISTER_CARRIES_WEEK = False` removes every new key and column.

## 2. The facts the plan rests on (all verified)

| Claim in the brief | What the source actually says |
|---|---|
| `_write_site(...)` writes data.json, index.html and trials.json from one scope | The function is **`_write_guild`** (`build.py:4525-4656`). It receives `inputs: _GuildInputs`, `week: dict`, `week_maxbuff`, `week_draw`, `draw_warning`, `ladder`. It writes `data.json` from `inputs.register` (`:4555-4557`), `index.html` via `_render_html(inputs.register, site)` (`:4558-4560`), `trials.json` from `week` (`:4566-4568`). **Confirmed: no new plumbing** — `inputs.register`, `week` and `draw_warning` are already in one scope. |
| Provenance is attached to all three artefacts | `build.py:4546-4552`: one `_provenance_block(inputs)` assigned onto `inputs.register`, `week`, `week_maxbuff`, `plan_dict` **before** any file is written. The new attach follows the same pattern and the same position. |
| `week` may be absent | Not from `main()`: `week = span[0]["week"]` (`:4805`) is always `WeekResult.to_dict()` (`_compute_unit`, `:4450`). A missing/stale **draw** is the real degraded path: `_load_draw` (`:4659-4696`) falls back to `config.TRIAL_SKILLS_CURRENT` (`config.py:519`) with `date="unknown"` and a non-empty `draw_warning`, which `trials.html` shows as a banner (`:2380-2385`). A guild whose *fetch* fails is simply absent from `fetched` (`:4766-4789`) and writes nothing at all. An optimiser exception propagates from `_run_units` (`:4749`) and fails the whole build — unchanged, out of scope. |
| `week["bench"]` shape | `list[str]` of member names: `bench=[m.name for m in assignment.bench]` (`trials.py:2631`), serialised verbatim (`:2442`). |
| Names are matched by `name` string | The two sides are **different exports**. The register is built from the *unmerged* member rows — for SC the gid=0 CSV (`process(parse(fetch_csv()))`, `build.py:4265`), for LI the gviz member tab (`process(gd.members)`, `:4271`). The trials seat the roster-**merged** list (`roster_model.merge`, `:4314`), which keeps each manual member's own `name` (`roster.py:645`) and **appends roster-only members** the member tab has never heard of (`roster.py:664-670`; live today: `AmamiyaKokoro` on SC, five names on LI per README:90-96). Those admitted members must **not** get a register row — `index.html` mirrors the officers' tab by rule (`processor.py:24-27`, README:94-96). The shared normaliser is `reader.norm_name` (`reader.py:189-204`, casefold + collapsed whitespace); `roster.join` applies it exact-first with an ambiguity rule (`roster.py:319-358`). |
| `week_date` identifies the week | It is the **build date**: `week_date=now.strftime("%Y-%m-%d")` (`trials.py:2616`). The draw source carries no cycle date — `TrialDraw.date` "is always `""`" (`draw.py:128-153`). `trials.html` headlines it as "Week of …" (`build.py:2596`) anyway, so the block copies it as-is and the contract says what it is. |
| `data.json` shape is pinned by tests | `test_data_json_is_byte_identical_with_roster_off` (`tests/test_roster.py:486`) and the gear twin (`tests/test_gear.py:508`) pin **`processor.process` output**, not the written file. This change is downstream of `process()` (in `_write_guild`), so both stay green untouched. |
| Consumers of `data.json` | None in-repo (`tampermonkey/` is empty; `apps-script/` reads the sheet, not the site). README:38-39 documents the file. Contract is therefore additive-only, stated in §4.3. |

Sizes today: `_site/data.json` 191,182 B; `_site/trials.json` 66,604 B.

## 3. The one design decision worth arguing about

**Both (option c): a top-level `week` block AND a per-member `trial` stamp.**

- The stamp alone fails the admitted members: `AmamiyaKokoro` is seated but has no
  register row, so there is nowhere to stamp — the block's party lists are the only
  place the register can name them without breaking the "mirror the officers' tab" rule.
- The block alone fails the consumer: a script that knows its own name would still
  walk four lists. The stamp is the O(1) answer.
- Neither is a copy of `trials.json`: no rates, tools, timelines or probes. The block
  is ~3 KB and the stamps ~9 KB pretty-printed (§11, R2).

Rejected: passing `week` into `_render_html` as a new parameter. The register dict is
already what the page renders from, and `provenance` reached the page the same way
(`build.py:4547`); one more key on the dict keeps `_render_html(data, site)` unchanged
for any caller and makes "page shows exactly what the JSON says" true by construction.

Rejected: a config flag being YAGNI. Every feature in this repo has a one-line switch
whose comment says what `False` restores (`TRIALS_BUFF_LEVEL_SLIDER`, `config.py:1420`;
`TRIALS_PUBLISH_MAXBUFF_PAGE`, `:1440`). The rollback section needs one, and a test
can pin that `False` is byte-identical on the API.

## 4. The JSON contract (exact)

### 4.1 Top-level `data.json["week"]` — `object | null`

Present iff `config.REGISTER_CARRIES_WEEK` is `True`. `null` iff the attach was given
no week (unreachable from `main()` today, §2; the contract still says what it means).

| key | type | source (`week` = the `trials.json` dict) | notes |
|---|---|---|---|
| `generated_at` | `str` | `week["generated_at"]` | ISO-8601 UTC; **the currency check**. Equal to `trials.json`'s, so a consumer can prove the two files are one build. |
| `week_date` | `str` | `week["week_date"]` | The **build** date (`trials.py:2616`), as `trials.html` already headlines it. |
| `skills` | `list[str]` | `list(week["skills"])` | The draw, in sheet-column order (`draw.py:131-136` — order carries no priority). |
| `draw_stale` | `bool` | `bool(draw_warning)` | `True` when `_load_draw` fell back to the last known draw. |
| `draw_warning` | `str` | `draw_warning` | The banner text `trials.html` shows, verbatim; `""` when the draw was read live. |
| `community_buff_level` | `int` | `week["community_buff_level"]` | Which regime this is (`trials.py:2405-2419`). |
| `total_points` | `int` | `week["total_points"]` | Banked step points. |
| `total_credit_points` | `float` | `week["total_credit_points"]` | The objective's currency. |
| `parties` | `list[object]` | one per `week["trials"][i]`, same order | see below |
| `bench` | `list[str]` | `list(week["bench"])` | Members the optimiser saw and did not seat. |
| `not_on_register` | `list[str]` | computed | Seated or benched names with **no register row** (the admitted roster-only members). Listed here because the register cannot carry a row for them — never dropped. |
| `unassigned` | `list[str]` | computed | Register members the optimiser **neither seated nor benched**. Expected `[]` in every normal build (`roster.merge` copies every manual member, `roster.py:622-660`); non-empty prints a WARNING (step 5). |

Each `parties[i]`:

| key | type | source |
|---|---|---|
| `skill` | `str` | `t["skill"]` |
| `party_size` | `int` | `t["party_size"]` |
| `tier_reached` | `int` | `t["tier_reached"]` |
| `points` | `int` | `t["points"]` |
| `credit_points` | `float` | `_credit_points(t)` (`build.py:706-716`, falls back to `points` when absent) |
| `clear_probability` | `float \| null` | `t.get("clear_probability")` |
| `members` | `list[str]` | `[r["name"] for r in _sorted_roster(t)]` (`build.py:697-704`, rate at final tier descending — the trials page's own default order, so the two pages name a party in the same order) |

### 4.2 Per-member `data.json["members"][i]["trial"]` — `object`

Present on **every** register member iff `week` is a non-null object; absent otherwise.

| key | type | values |
|---|---|---|
| `skill` | `str \| null` | the party's skill when `status == "assigned"`; `null` otherwise |
| `status` | `str` | `"assigned"` (in a party) · `"bench"` (in `week["bench"]`) · `"unassigned"` (the optimiser never saw this name — a data anomaly, also listed in `week.unassigned`) |

Consumer recipe: `m = data.members.find(m => m.name === me); m?.trial?.skill` gives the
skill or `null`; `data.week.draw_stale` and `data.week.generated_at` say whether to
trust it. A name absent from `members` but present in `data.week.not_on_register` is a
roster-only member — look them up in `data.week.parties[*].members`.

### 4.3 Backward compatibility — additive only

- Every key `data.json` carries today (`generated_at`, `member_count`, `skills`,
  `skill_summary`, `members`, `provenance`; per member `name`, `main_classes`, `flex`,
  `flex_levels`, `skills`, plus the optional roster fields) is **unchanged in name,
  type, order and value**. The only additions are `week` and `members[i].trial`.
- `member_count` stays the register's count (108 on SC today). It is **not** the seat
  count (109 = 108 + 1 admitted): `sum(p.party_size) + len(bench)` is the seat count.
  The contract says so rather than changing a published number.
- Pinned by `test_flag_off_is_byte_identical_and_on_is_additive` (§10).

### 4.4 What does not change

- `trials.json` — the attach reads from `week` and **copies** (`list(...)`, fresh
  dicts); nothing is written into `week`. Pinned by
  `test_the_block_copies_and_trials_json_is_untouched` and the `_write_guild` test.
- `signup.json`, `trials-maxbuffs.*`, `signup.html` — untouched.
- No register **row** is added for an admitted member (README:94-96).

## 5. The join rule

`roster.join`'s rule, applied register → seats (`roster.py:319-358`):

1. Build `seat: {name: (skill|None, status)}` from `week["trials"][*]["roster"][*]["name"]`
   (status `"assigned"`), then `week["bench"]` (`"bench"`), first insertion wins.
2. A **normalised key** (`reader.norm_name`) held by two distinct raw names on
   **either** side is ambiguous and matches nobody through normalisation.
3. For each register member: exact `name in seat` wins; else, if its key is not
   ambiguous, `by_norm.get(key)`; else no hit.
4. Hit → stamp `{skill, status}` and mark the seat name claimed. Miss → stamp
   `{"skill": null, "status": "unassigned"}` and append to `unassigned`.
5. `not_on_register` = seat names never claimed, in seat insertion order (parties in
   draw order, then bench) — deterministic, so a rebuild of the same week diffs clean.

Why a normalised fallback when the live join is exact today (108/108 on SC): the two
sides are different exports (§2), and this repo has measured what exact-only joins cost
on these sheets — "six members per guild to nothing but capitalisation drift"
(`roster.py:322-324`). One shared normaliser, by design (`reader.py:196-203`).

## 6. The page (`index.html`, `_render_html`, `build.py:537-661`)

Everything below is conditional on `data.get("week") is not None`; with the flag off or
`week: null` the markup is exactly today's.

1. **Stale banner** — first thing inside `<main>`, the same `.alert` as `trials.html`
   (`build.py:2380-2385`, CSS `:2463-2465`), same reason: "so a fallback draw can never
   be mistaken for a live one".
2. **"This week's trials" section** — before "Per-skill summary": an `<h2>`, a `.meta`
   line ("Week of {week_date} · {skills} · bench: … · full detail on the Guild Trials
   page"), a `.meta` line "Also seated, but not on this tab: …" when `not_on_register`
   is non-empty (nobody dropped on the page either), and a 4-column table in the page's
   existing `.scroll > table` idiom: Skill | Party | Tier | Credit pts (`_cp`,
   `build.py:1627`).
3. **`Trial` column** in the Members table, after Flex and before the skills: the skill
   name, or `bench` / `unassigned` in muted italics.

Two CSS rules are added to the page's `<style>` (`.alert`, `.trialcell.muted`) and
`--warn` to `:root`. With the flag off these are inert — the page differs from today by
those rules only, which is why the byte-identity pin (§10) is on the **JSON key set**
and the page pin is "no `Trial` column, no alert, no section".

## 7. Degraded paths — what `data.json` and `index.html` carry

| situation | where it is decided | `data.json` | `index.html` |
|---|---|---|---|
| Live draw, normal | — | `week` block, `draw_stale: false`, stamps on all members | section + column, no banner |
| Draw unreadable → fallback (`_load_draw`, `build.py:4659-4696`) | `draw_warning != ""` | block present, **`draw_stale: true`**, `draw_warning` = the text `trials.html` banners; stamps present — they are what `trials.json`/`trials.html` publish behind the same banner (three artefacts, one story) | the same "Draw may be stale." banner, first in `<main>` |
| Sign-up plan withheld / stale sign-up tab (`build.py:4361-4392`) | `inputs.picks is None` | **no effect** — the published week is the full optimum over all members; `_compute_unit` runs `run_week` with no picks (`:4432-4448`) | no effect |
| Roster tab unavailable or refused (`build.py:4287-4310`, `roster.py:605-618`) | `members` = manual rows | block present; `not_on_register == []` (nobody admitted) | as normal |
| Optional guild's fetch fails (`build.py:4766-4789`) | LI absent from `fetched` | **nothing written to `_site/li/`** — unchanged behaviour; the whole `_site` still deploys | none |
| Optimiser unit raises (`build.py:4749`) | `f.result()` | build exits non-zero, deploy blocked for both guilds — **unchanged, out of scope** (no optimiser changes) | — |
| `week is None` (unreachable from `main()`) | `_attach_week` | `"week": null`, **no** `trial` stamps | exactly today's page |
| `config.REGISTER_CARRIES_WEEK = False` | step 5 guard | no `week` key, no `trial` keys — today's contract | today's markup + two inert CSS rules |

The register still builds and publishes in every row of this table: the attach is pure
dict work over keys `WeekResult.to_dict()` always writes (`trials.py:2431-2461`), uses
`.get` for the two optional ones, and raises on nothing the optimiser can produce.

## 8. Files touched

| file | change |
|---|---|
| `src/config.py` | `REGISTER_CARRIES_WEEK = True`, after `TRIALS_PUBLISH_MAXBUFF_PAGE` (`:1440`), before `# --- Build concurrency` (`:1442`). ~14 lines incl. comment. |
| `src/build.py` | `from collections import Counter` (imports, `:9-27`); `norm_name` added to the `reader` import (`:27`); new `_attach_week` before `_render_html` (`:537`); `_render_html` gains banner/section/column (`:537-661`); `_write_guild` calls the attach + prints the WARNING between `:4552` and `:4554`. ~130 lines, no signature changes. |
| `tests/test_register_week.py` | **NEW.** Ten tests (§10). |
| `README.md` | Step 4 of "What it does" (`:38-40`) mentions the block; new `### data.json carries this week's assignments` after "Pinned members" (before `## Sign-up optimiser`, `:492`). ~30 lines. |

Not touched: `src/trials.py`, `src/optimizer.py`, `src/signup.py`, `src/roster.py`,
`src/reader.py`, `src/processor.py`, `.github/workflows/deploy.yml`.

## 9. Steps

**Prerequisites.**
`git status` shows unrelated uncommitted edits to `src/config.py`, `apps-script/`,
`research/`, `.claude/plans/…`. Checkpoint before starting and stage **only** this
change's files at the end (`git add src/build.py src/config.py tests/test_register_week.py README.md .claude/plans/weekly-assignments-on-register-implementation-plan.md` — use `git add -p src/config.py` so the pending config edits are not swept in). Record `git rev-parse HEAD` as the rollback anchor.

### Step 1 — the switch (`src/config.py`, after line 1440)  ~3 min

```python
# The register (index.html + data.json) CARRIES this week's assignments: a compact
# `week` block (parties as name lists, the bench, the draw and whether it may be
# stale) and a `trial` stamp on every member. A projection of trials.json, not a copy
# — no rates, tools or timelines — so that one fetch of data.json answers both "what
# does each member have" and "what is each member doing this week"; the in-game
# script that asked for this has one request to spend. trials.json is unchanged and
# stays the full record. See build._attach_week.
#
# False is the one-line rollback: no `week` key, no `trial` keys, no Trial column —
# data.json's key set exactly as before, pinned by
# tests/test_register_week.py::test_flag_off_is_byte_identical_and_on_is_additive.
REGISTER_CARRIES_WEEK = True
```

Verify: `.venv/bin/python -c "from src import config; assert config.REGISTER_CARRIES_WEEK is True"`.

### Step 2 — imports (`src/build.py:9-27`)  ~1 min

Add `from collections import Counter` among the stdlib imports (`:9-17`); change `:27` to
`from .reader import MemberRow, SheetStructureError, fetch_csv, norm_name, parse`.

Verify: `.venv/bin/python -c "import src.build"`.

### Step 3 — the projection (`src/build.py`, new function immediately before `_render_html`, currently `:537`)  ~15 min

```python
def _attach_week(register: dict, week: Optional[dict], draw_warning: str) -> None:
    """Project this week's assignments onto the register, in place.

    data.json and index.html answer "what does each member have"; trials.json answers
    "what is each member doing this week". A reader who wanted both fetched both, and
    the in-game script that motivates this has one fetch to spend. So the register now
    CARRIES a compact projection of the week: a top-level ``week`` block (the parties as
    name lists, the bench, the draw, whether it may be stale) and a per-member ``trial``
    stamp. trials.json is untouched and stays the full record — this copies OUT of
    ``week`` and never aliases into it, so nothing done to the register can leak back.

    THE JOIN IS BY NAME, exact first and then ``reader.norm_name``, under ``roster.join``'s
    ambiguity rule: a normalised key held by two distinct names on EITHER side matches
    nobody through normalisation. The two sides are different exports — the register is
    the UNMERGED member tab (for SC the gid=0 CSV; ``_fetch_guild``) and the trials seat
    the roster-MERGED members, which include roster-only members the tab has never heard
    of. Neither side is dropped: a seated name with no register row goes in
    ``not_on_register`` (the register may not grow a row for it — index.html mirrors the
    officers' tab, README "Where member data comes from"), and a register member the
    optimiser never saw is stamped ``unassigned`` and listed, which should not happen
    (``roster.merge`` copies every manual member) and is a WARNING when it does.

    ``week_date`` is copied as trials.json carries it — the BUILD date (trials.run_week),
    the draw source publishing no cycle date (draw.TrialDraw). A consumer that wants to
    know whether this block is current compares ``generated_at`` with trials.json's.
    """
    if week is None:
        register["week"] = None
        return

    # Who is where: seated names in draw order (a member is in at most one party by
    # construction), then the bench. Insertion order is kept for every list below so a
    # rebuild of the same week diffs clean.
    seat: dict[str, tuple[Optional[str], str]] = {}
    for trial in week["trials"]:
        for entry in trial["roster"]:
            seat.setdefault(entry["name"], (trial["skill"], "assigned"))
    for name in week.get("bench") or []:
        seat.setdefault(name, (None, "bench"))

    members = register["members"]
    ambiguous = {
        k for k, c in Counter(norm_name(n) for n in seat).items() if c > 1
    } | {
        k for k, c in Counter(norm_name(m["name"]) for m in members).items() if c > 1
    }
    by_norm: dict[str, str] = {}
    for name in seat:
        by_norm.setdefault(norm_name(name), name)

    claimed: set[str] = set()
    unassigned: list[str] = []
    for m in members:
        hit = m["name"] if m["name"] in seat else None
        if hit is None and norm_name(m["name"]) not in ambiguous:
            hit = by_norm.get(norm_name(m["name"]))
        if hit is None:
            m["trial"] = {"skill": None, "status": "unassigned"}
            unassigned.append(m["name"])
        else:
            skill, status = seat[hit]
            m["trial"] = {"skill": skill, "status": status}
            claimed.add(hit)

    register["week"] = {
        "generated_at": week["generated_at"],
        "week_date": week["week_date"],
        "skills": list(week["skills"]),
        "draw_stale": bool(draw_warning),
        "draw_warning": draw_warning,
        "community_buff_level": week["community_buff_level"],
        "total_points": week["total_points"],
        "total_credit_points": week["total_credit_points"],
        "parties": [
            {
                "skill": t["skill"],
                "party_size": t["party_size"],
                "tier_reached": t["tier_reached"],
                "points": t["points"],
                "credit_points": _credit_points(t),
                "clear_probability": t.get("clear_probability"),
                # The trials page's own default order (rate at the final tier,
                # descending), so the two pages name a party in the same order.
                "members": [r["name"] for r in _sorted_roster(t)],
            }
            for t in week["trials"]
        ],
        "bench": list(week.get("bench") or []),
        "not_on_register": [n for n in seat if n not in claimed],
        "unassigned": unassigned,
    }
```

Verify: `.venv/bin/python -c "import src.build as b; r={'members':[{'name':'a'}]}; b._attach_week(r, None, ''); assert r['week'] is None and 'trial' not in r['members'][0]"`.

### Step 4 — the page (`src/build.py`, `_render_html`, `:537-661`)  ~20 min

Edits inside the existing function; the signature `_render_html(data: dict, site: "GuildSite") -> str` does not change.

1. After `skills = data["skills"]` (`:538`):
   ```python
   # This week's assignments, when the register carries them (_attach_week). None or
   # absent renders the page exactly as it was: no banner, no section, no column.
   week = data.get("week")
   ```
2. Before `member_rows = []` (`:556`): `trial_header = "<th>Trial</th>" if week is not None else ""`.
3. In the member loop, after the Flex cell (`:562`) and before the skills loop (`:563`):
   ```python
   if week is not None:
       stamp = m.get("trial") or {"skill": None, "status": "unassigned"}
       label = stamp["skill"] or stamp["status"]
       cls = "trialcell" if stamp["skill"] else "trialcell muted"
       cells.append(f'<td class="{cls}">{html.escape(label)}</td>')
   ```
4. Before the `return f"""…` (`:579`), build `alert_html` and `week_section`:
   ```python
   alert_html = ""
   week_section = ""
   if week is not None:
       if week["draw_stale"]:
           # The same banner trials.html shows, for the same reason: first thing on
           # the page, so a fallback draw cannot be mistaken for a live one.
           alert_html = (
               '<div class="alert" role="alert"><strong>Draw may be stale.</strong> '
               f"{html.escape(week['draw_warning'])}</div>"
           )
       party_rows = "".join(
           "<tr>"
           f"<td>{html.escape(p['skill'])}</td>"
           f"<td class=num>{p['party_size']}</td>"
           f"<td class=num>{p['tier_reached']}</td>"
           f"<td class=num>{_cp(p['credit_points'])}</td>"
           "</tr>"
           for p in week["parties"]
       )
       bench_note = (
           " &middot; bench: " + html.escape(", ".join(week["bench"]))
           if week["bench"] else ""
       )
       # Roster-only members are seated but have no row here (index.html mirrors
       # the officers' tab). Named, so the page drops nobody either.
       extra_note = (
           '<p class="meta">Also seated, but not on this tab: '
           f"{html.escape(', '.join(week['not_on_register']))}.</p>"
           if week["not_on_register"] else ""
       )
       week_section = f"""
  <h2>This week's trials</h2>
  <p class="meta">Week of {html.escape(week['week_date'])} &middot;
     {html.escape(', '.join(week['skills']))}{bench_note} &middot;
     full detail on the <a href="trials.html">Guild Trials</a> page.</p>
  {extra_note}
  <div class="scroll">
    <table>
      <thead><tr><th>Skill</th><th class=num>Party</th><th class=num>Tier</th>
                 <th class=num>Credit pts</th></tr></thead>
      <tbody>{party_rows}</tbody>
    </table>
  </div>
"""
   ```
5. In the template: add `--warn: #e0b341;` to `:root` (`:586-590`); add the two rules
   after `.nav a:hover` (`:620`):
   ```
   .alert {{ background: #2a1f10; border: 1px solid var(--warn); color: #f2dca6;
             border-radius: 8px; padding: .8rem 1rem; margin: 0 0 1.25rem;
             font-size: .9rem; }}
   .trialcell.muted {{ color: var(--muted); font-style: italic; }}
   ```
   (double braces — the page is one f-string). Change `<main>` (`:632`) to
   `<main>\n  {alert_html}{week_section}` and the Members header (`:650`) to
   `<tr><th>Member</th><th>Main</th><th>Flex</th>{trial_header}{skill_headers}</tr>`.

Verify: `.venv/bin/python -c "import src.build as b, src.processor as p; from tests.test_roster import _member; r=p.process([_member('a')]); h=b._render_html(r, b.GUILD_SITES[0]); assert '<th>Trial</th>' not in h and 'alert' not in h.split('<body>')[1]"`.

### Step 5 — the hook (`src/build.py`, `_write_guild`, between `:4552` and `:4554`)  ~5 min

```python
    # --- This week's assignments, projected onto the register ------------------
    # After the provenance block and before data.json / index.html are written, so
    # the register carries both. Gated: config.REGISTER_CARRIES_WEEK = False is the
    # byte-for-byte rollback of the API (no new keys, no Trial column).
    if config.REGISTER_CARRIES_WEEK:
        _attach_week(inputs.register, week, draw_warning)
        stamped = inputs.register["week"]
        if stamped is not None and stamped["unassigned"]:
            # Should never fire: roster.merge copies every manual member, so every
            # register name ought to be seated or benched. If it does, the register
            # export and the member tab disagree on a name — actionable, so loud,
            # like the sign-up join's WARNING below.
            print(
                f"WARNING ({site.key}): {len(stamped['unassigned'])} member(s) on the "
                f"'{site.member_tab}' tab were neither seated nor benched and are "
                f"stamped 'unassigned' in data.json: "
                + ", ".join(stamped["unassigned"]),
                file=sys.stderr,
            )
```

Verify: covered by step 6's `_write_guild` tests; and `.venv/bin/python -m pytest tests/test_roster.py tests/test_gear.py -q -k byte_identical` still passes (the pins are upstream of this hook).

### Step 6 — tests (`tests/test_register_week.py`, new)  ~30 min

See §10 for the functions. Verify: `.venv/bin/python -m pytest tests/test_register_week.py -q` → 10 passed; then the full suite → 439 passed.

### Step 7 — README  ~10 min

- `:38-40`: "**Build** `_site/index.html` … and `_site/data.json` — which since
  2026-09 also carries this week's assignments (see below) — once per guild …".
- New `### data.json carries this week's assignments` after "Pinned members" (before
  `:492`): the §4 tables condensed to one paragraph and one key list; the consumer
  recipe from §4.2; the `member_count` ≠ seat count note; the
  `REGISTER_CARRIES_WEEK` rollback line.

Verify: read it back; no claims beyond §4.

### Step 8 — live build and the end-to-end assertion  ~15 min

```bash
cd /Users/morgan/pie/farm/guild && .venv/bin/python -m src.build
.venv/bin/python - <<'EOF'
import json, os
for d in ("_site", "_site/li"):
    data = json.load(open(f"{d}/data.json")); week = data["week"]
    pub = json.load(open(f"{d}/trials.json"))
    assert week["generated_at"] == pub["generated_at"] and week["skills"] == pub["skills"]
    seated = {n for p in week["parties"] for n in p["members"]} | set(week["bench"])
    assert seated == {r["name"] for t in pub["trials"] for r in t["roster"]} | set(pub["bench"])
    assert all("trial" in m for m in data["members"]), d
    assert week["unassigned"] == [], (d, week["unassigned"])
    # The names with no register row are exactly the roster-admitted members.
    assert set(week["not_on_register"]) == set(data["provenance"]["admitted_names"]), d
    assert "week" not in pub and "trial" not in json.dumps(pub)
    for p, t in zip(week["parties"], pub["trials"]):
        assert p["party_size"] == t["party_size"] == len(p["members"])
    print(d, "ok:", len(seated), "seated;", data["member_count"], "on register;",
          "not_on_register", week["not_on_register"], ";",
          os.path.getsize(f"{d}/data.json"), "bytes")
EOF
grep -c "<th>Trial</th>" _site/index.html _site/li/index.html   # 1 and 1
```

Expected on today's data: SC `not_on_register == ["AmamiyaKokoro"]`, LI the five
admitted names; `data.json` ≈ 191 KB → ≈ 203 KB (R2). Then commit
(`feat(register): data.json and index.html carry this week's assignments`) with the
files listed under Prerequisites only.

**Total: ~100 min** plus one local build (~3-4 min).

## 10. Test plan — `tests/test_register_week.py`

Helpers (module-level, following `tests/test_roster.py:339-349` and
`tests/test_trials.py:1359-1367`):

```python
import copy, html, json
from src import build, config, processor, trials
from src.reader import MemberRow, SkillEntry

SKILLS = ["Foraging", "Brewing"]   # two trials; cap=4 over ten members leaves a bench

def _member(name, level=100):
    return MemberRow(name=name, main_classes="", flex="", flex_levels=[], skills={
        s: SkillEntry(level=level, tool=False, top=False, bot=False, house=4)
        for s in config.SKILLS})

def _ten():
    return [_member(f"m{i}", 90 + i) for i in range(10)]

def _week(members, cap=4):
    """Deterministic: trials.run_week (trials.py:2662) with a fixed seed, random split."""
    return trials.run_week(members, skills=list(SKILLS), seed=7, cap=cap,
                           strategy="random").to_dict()

def _inputs(site, members, register):
    return build._GuildInputs(site_key=site.key, members=members, register=register,
                              picks=None, signup_unavailable="not in this test",
                              signup_unavailable_short="test")
```

| test | what it pins |
|---|---|
| `test_every_register_member_is_stamped_exactly_once` | assigned ∪ bench partitions the ten; each stamp agrees with the block; `parties[i].members == [r.name for r in _sorted_roster(week.trials[i])]`; `party_size == len(members)`; `unassigned == not_on_register == []`. |
| `test_the_block_copies_and_trials_json_is_untouched` | `json.dumps(week, sort_keys=True)` identical before/after `_attach_week`; mutating `register["week"]["bench"]` and a party list leaves `week` unchanged (no aliasing). |
| `test_a_seated_name_with_no_register_row_is_listed_not_dropped` | register = nine, week over nine + `"AmamiyaKokoro"` → the name is in some party/bench list, `not_on_register == ["AmamiyaKokoro"]`, and `register["members"]` gained **no row**. |
| `test_a_register_member_the_optimiser_never_saw_is_unassigned_and_warned` | register = ten + `"ghost"`, week over ten → `ghost.trial == {"skill": None, "status": "unassigned"}`, `unassigned == ["ghost"]`; and through `_write_guild` (tmp `OUTPUT_DIR`) `capsys.readouterr().err` contains `"stamped 'unassigned'"` and `"ghost"`. |
| `test_the_join_is_case_insensitive_but_refuses_ambiguity` | week seats `"Dome"` + m0..m8; register `"dome"` + m0..m8 → matched (`not_on_register == []`); register `"dome"`, `"DOME"` + m0..m8 → both `unassigned`, `not_on_register == ["Dome"]` (`roster.join`'s rule, `roster.py:325-329`). |
| `test_a_stale_draw_is_flagged_in_the_block_and_bannered_on_the_page` | `draw_warning="…MAY BE STALE…"` → `draw_stale is True`, text copied; `_render_html` contains `Draw may be stale.` **before** `This week's trials`; with `""` → `False` and no banner. |
| `test_the_register_page_shows_the_trial_column_and_section` | `<th>Trial</th>` present; a benched member renders `class="trialcell muted">bench<`; an assigned one `class="trialcell">Foraging<` or `Brewing<`; `Also seated, but not on this tab` appears iff `not_on_register` is non-empty. |
| `test_week_none_writes_null_and_renders_the_page_as_before` | `_attach_week(register, None, "")` → `register["week"] is None`, no `trial` keys, `_render_html` output `==` the page rendered from a deep copy taken before. |
| `test_write_guild_publishes_the_week_on_both_guilds_and_leaves_trials_json_alone` (`tmp_path`, `monkeypatch.setattr(build, "OUTPUT_DIR", tmp_path)`) | for each `build.GUILD_SITES`: `_write_guild(site, _inputs(...), week, None, build.draw_model.TrialDraw(skills=SKILLS, date=""), "")`; `data.json` has `week` and stamps; `set(trials.json) == keys_of_week_before_call | {"provenance"}`; `"trial" not in json.dumps(trials.json)`; `data["provenance"] == published["provenance"]`; both `tmp_path/data.json` and `tmp_path/li/data.json` exist. |
| `test_flag_off_is_byte_identical_and_on_is_additive` (`tmp_path`, `monkeypatch`) | run `_write_guild` with `config.REGISTER_CARRIES_WEEK` False then True: `set(off) == {"generated_at","member_count","skills","skill_summary","members","provenance"}`; `set(on) - set(off) == {"week"}`; per member `set(on_m) - set(off_m) == {"trial"}`; `"<th>Trial</th>"` absent from the off page, present on the on page; `class="alert"` absent from the off page. |

Ten tests, ~12 `run_week` calls on ten members × two skills — the same size
`tests/test_trials.py::_two_regime_weeks` already runs; expect well under 30 s.
`_write_guild` is exercised for real (it renders `trials.html` and the inactive
`signup.html` into `tmp_path`; both are pure). Nothing reads the network or the clock
beyond `generated_at`.

## 11. Risks

**R1 — name-join mismatch.** *Probability medium, impact medium.* Two exports, casing
drift on every sheet, and roster-only members. *Mitigation:* exact-then-`norm_name`
with the ambiguity rule (§5), `not_on_register` and `unassigned` lists so nothing
vanishes, a WARNING on `unassigned`, five tests. *Detection:* step 8's live assertion
`set(not_on_register) == set(provenance.admitted_names)` — any other name there is a
join miss. *Contingency:* the stamp says `unassigned`, never a wrong skill.

**R2 — `data.json` payload growth.** *Probability certain, impact low.* Measured
today: 191,182 B. Estimate: stamps ≈ 108 × ~80 B pretty-printed ≈ 8.6 KB; block ≈ 109
names + 4 party summaries ≈ 3 KB → **≈ +12 KB, ≈ +6 %**. *Mitigation:* names only, no
rates or timelines (the block is a projection); Pages gzips JSON. *Threshold:* step 8
prints the size; if growth exceeds 10 %, drop `clear_probability`/`points` from parties
before shipping — nothing else is optional.

**R3 — stale or absent week presented as current.** *Probability low, impact high.*
A fallback draw (§7) or a consumer holding an old `data.json` beside a new
`trials.json`. *Mitigation:* `draw_stale` + verbatim `draw_warning` in the block, the
same banner on `index.html` as on `trials.html`, and `generated_at` equal across the
two files so a consumer can prove they are one build; README tells consumers to check
both. `week_date` is documented as the build date so nobody reads it as a cycle id.
Tested by the stale-draw test.

**R4 — breaking an existing `data.json` consumer.** *Probability low, impact high.*
*Mitigation:* additive keys only; `member_count` unchanged (§4.3); `_render_html`
signature unchanged; pinned by the flag test's key-set assertions.

**R5 — leaking into `trials.json`.** *Probability low, impact high* (it is the
authoritative record). *Mitigation:* the attach copies (`list(...)`, fresh dicts) and
never writes to `week`; two tests assert the dict and the written file are unchanged.

**R6 — the pending `src/config.py` edits.** *Probability medium, impact low.* The file
already has uncommitted changes. *Mitigation:* `git add -p src/config.py`; the commit
diff for that file must be the one constant and its comment.

**R7 — the byte-identity and golden pins.** *Probability low.* Both pin
`processor.process` / `run_week` output, upstream of `_write_guild`; the full suite in
step 6 proves it (429 → 439 passed, none changed).

**If implementation gets stuck:** the attach is ~60 lines of dict work; the page is the
fiddly half (f-string braces). Ship the JSON first (steps 1-3, 5, tests minus the two
page tests), then the page — the flag and the `week is not None` guards make that a
valid intermediate state.

## 12. Rollback

**Immediate (one line, no code):** `REGISTER_CARRIES_WEEK = False` in `src/config.py`,
push to `main`. `data.json` regains exactly today's key set and `index.html` loses the
column, section and banner (pinned by the flag test). ~30 s to edit; the deploy is the
usual CI run.

**Full (code):** `git revert <commit>` (the single commit from step 8), or
`git reset --hard <anchor>` before it is pushed. Confirm with
`.venv/bin/python -m pytest tests/ -q` (429 passed, `tests/test_register_week.py` gone)
and `python3 -c "import json; d=json.load(open('_site/data.json')); assert 'week' not in d"`
after a rebuild.

**Partial:** keep the JSON, drop the page — delete the `week`-conditional fragments
in `_render_html` (step 4); or keep the page markup, drop the projection — remove the
step-5 hook and `_render_html` falls back to today's page because `data.get("week")`
is `None`. Each half is independently inert.

**Triggers:** any `unassigned` WARNING on a live build (a join miss); `data.json`
growth > 10 %; a consumer report of a changed existing key (should be impossible —
the flag test would have caught it); any red in the suite.

## 13. Success criteria

- `_site/data.json` and `_site/li/data.json` each carry `week` (§4.1) and a `trial`
  stamp on every member (§4.2); step 8's assertions pass on live data with
  `unassigned == []` and `not_on_register` equal to the admitted names.
- `_site/trials.json` and `_site/li/trials.json` are unchanged in key set and content
  relative to a build of the same inputs without the change.
- `index.html` for both guilds shows the section and the `Trial` column; a fallback
  draw shows the banner first.
- `tests/test_register_week.py` passes; the full suite passes with no existing test
  modified.
- `REGISTER_CARRIES_WEEK = False` reproduces today's `data.json` key set.
- Every non-obvious choice in the new code carries its reasoning in a comment
  (the join rule, the copy-not-alias rule, the `week_date` caveat, the gate).

Quality checklist: no signature changed · no optimiser/`trials.py` change · additive
JSON only · stderr WARNING for the one anomaly that is actionable · README updated ·
only this change's files staged.

## 14. Metadata

- Created 2026-09-08 against `842faeb`; anchors are line numbers in the working tree.
- Agent: implementation-planner. DeepWiki: not applicable (no external library).
- Complexity: low-medium (one new pure function, one renderer extension, one hook).
- Risk: low — additive, gated, and every degraded path already exists upstream.
