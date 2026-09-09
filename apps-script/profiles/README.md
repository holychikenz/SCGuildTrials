# Guild profile roster write endpoint (Apps Script Web App)

Lets the in-game Tampermonkey modules push each member's **profile** — skills,
house levels, shrine purchases, skilling tools, achievements, progression points
— into its own tab of the guild sheet.

**Independent of the sign-up endpoint** (`../Code.gs`), deliberately. Sign-ups
and profile lookups are unrelated jobs with unrelated payloads, so they get
separate script projects, separate deployments and separate secrets:

| | script | writes | deployment |
|---|---|---|---|
| Sign-ups | `../Code.gs` | `SC Trial Signup`, `LI Trial Signup` | its own `/exec` URL |
| Profiles | `profiles/Code.gs` | `SC Roster`, `LI Roster` | its own `/exec` URL |

Tab names mirror each other across the two jobs — `SC`/`LI` for the guild, then
the job — so the guild is obvious at a glance and sign-ups never look like
rosters in the tab bar.

The benefit is blast radius: editing this file cannot break the live sign-up
pipeline, and needs no re-deploy of it. Neither script knows the other exists.

They also cannot be mistaken for one another if you paste the wrong URL into the
wrong module's settings — a sign-up payload has no `characterId` column and is
refused here (with a hint saying so), while a profile payload's header does not
begin with `User` and is refused there. The contracts guard themselves.

```
Game tab (Tampermonkey: guild-profile-store → guild-profile-sheet)
   │  guild-profile-store archives every profile card opened, VERBATIM,
   │    partitioned by the profile's own guildId
   │  guild-profile-sheet flattens ONE guild → { header, rows }, ~101 columns
   ▼  POST { secret, tab, mode, guildId, guildName, header, rows }
script.google.com/macros/s/<id>/exec   ← profiles/Code.gs, runs as the sheet OWNER
   ▼  UPSERTS on characterId (only tabs in ALLOWED_TABS)
per-guild tab, chosen by the rows' own guild id:
      Survey Corps        → "SC Roster"   (guild id 4)
      Lactose lntolerance → "LI Roster"   (guild id 240)
```

The modules live in the sibling repo:
`~/pie/farm/cowstuff/tampermonkey/src/modules/guild-profile-{store,sheet}/index.js`.

## Upsert, not overwrite — and why it must be

Profile cards are opened **one at a time, over days**. Any given write may carry
three members when the tab already holds forty. So rows are matched on
`characterId` and updated in place, unknown ids are appended, and **members
absent from the payload are left untouched**.

This is the opposite of the sign-up script, and correctly so: there, one
`guild_characters_updated` message carries the *whole* roster, so clearing and
rewriting is safe. Doing that here would delete the thirty-seven members you
happened not to look at that session.

Rows key on the numeric **`characterId`**, never the name: names change (the game
carries a `previousName` field), and a renamed member would otherwise be appended
a second time instead of updated.

`mode:"replace"` is available for a deliberate full refresh — raise the module's
`minRows` first.

## One-time setup

1. **Create a new Apps Script project** at [script.google.com](https://script.google.com)
   → *New project*. Standalone, **not** bound to the spreadsheet: this file opens
   the sheet by id, and a separate project is what keeps the two deployments
   apart.
2. **Add the script.** Paste `Code.gs` in, replacing the default file.
3. **Set the secret.** Change `SHARED_SECRET` to a long random string, **different
   from the sign-up script's**. Until you do, every request is refused (a
   deliberate interlock).
4. **Create the tabs.** In the guild spreadsheet: **`SC Roster`** and
   **`LI Roster`**. The script refuses any tab not in `ALLOWED_TABS`, and never
   creates one. It *does* widen one — a new tab is 26 columns wide and a profile
   block is ~101.
5. **Deploy as a web app.** **Deploy → New deployment → Web app**:
   - **Execute as:** *Me* (the sheet owner)
   - **Who has access:** *Anyone*

   Authorise when prompted, then copy the **deployment URL** (ends in `/exec`).
6. **Configure the module** (in-game, MWIX command palette → *Guild Profile
   Sheet* → settings):
   - **Apps Script /exec URL** → the URL from step 5 (*not* the sign-up module's)
   - **Shared secret** → the exact string from step 3
   - **Force tab (override)** → leave empty (routes by guild)
   - **Guild id → profile tab map** → leave the default (`4 = SC Roster`,
     `240 = LI Roster`). The tab is chosen from the guild id of the rows
     themselves; add a line for any further guild.

## Verify

- **Health check:** open the `/exec` URL in a browser. You should see
  `{"ok":true,"service":"guild-profile-sheet","allowedTabs":[…],"keyColumn":"characterId"}`.
  If it says `"service":"guild-signup-sync"` you have the sign-up deployment.
- **Run the tests** (no dependencies; stubs `SpreadsheetApp`, so nothing touches
  the live sheet):
  ```bash
  cd ~/pie/farm/guild && node --test apps-script/profiles/Code.test.js
  ```
- **Dry run:** open a few profile cards in game, then palette → *Guild Profile
  Sheet* → panel → **Send to sheet** with **Dry run** on. It logs the exact block
  it would write.
- **Real write:** Dry run off, **Send to sheet** → the toast reads
  `✓ N updated, M added → 'SC Roster'`. Then open **one more** profile card and
  send again: the count should show that one added or updated, and every earlier
  row still present. That is the upsert working.

### There is no scratch tab, deliberately

The sign-up pipeline has `chikenz-test` because a sign-up write **clears the
block and rewrites it**, over a tab `guild/src/signup.py` parses — rehearsing
against a copy is plainly worth it there. This endpoint only ever **upserts**: a
mistaken write adds or updates rows and cannot wipe a tab, nothing downstream
reads these tabs, and a wrong header is refused rather than written through. So
**Dry run** is the rehearsal mechanism, and writes go straight to the real tab.

The one thing to get right first time is the **column set**, because the first
write bakes the header in and later writes with different column settings are
refused until you re-send with `mode:"replace"`. Settle the settings toggles
(exact XP, stable gear, ability levels, per-achievement columns) before the first
write, or just `replace` once when you change your mind.

## Re-deploying after an edit

Editing `Code.gs` does **not** change the live `/exec` behaviour until you
**Deploy → Manage deployments → (edit) → Version: New version → Deploy**. The
`/exec` URL stays the same across versions. This is a *different* deployment from
the sign-up script's, so re-deploying it leaves sign-ups alone entirely.

## Header drift

A write whose header **shifts** relative to the tab's existing header is
**refused**, naming the offending column — because a shifted column would write
(say) levels into XP cells for every row already on the tab. Toggling a column
block in the module's settings (exact XP, stable gear, ability levels,
per-achievement columns) shifts the header, so after such a change either
restore the previous settings or re-send once with `mode:"replace"`.

A header that merely **grows at the tail** is accepted: a payload column whose
sheet cell is still blank is a new column, not drift. This matters because the
remedy for a refusal is `mode:"replace"`, and replace destroys the accumulated
`gearSeen` union — so refusing a harmless column addition would push you
straight into the one action that loses data.

Note that a **narrower** payload is also harmless. `doPost` only ever addresses
the first *n* columns, where *n* comes from the payload, so reverting the
userscript to a build that does not send `gearSeen` leaves that column
completely untouched — read, written and cleared never. The union survives a
rollback with no export and no ritual. This is why `gearSeen` is the **last**
column and why no setting toggles it.

## The gear union (`gearSeen`)

Every other cell on a row is a snapshot, and the newest write wins. `gearSeen`
is the exception: it is the **union of every capture**, accumulated over months
and across machines.

Combat slots rotate with whatever a member is training, so one profile card
shows a fraction of their gear. The userscript sends what *this* capture saw of
a curated 200-item set — top-tier combat gear, every cape, every pouch, every
tool, and all skilling utility wherever it hides — as a JSON string:

```json
{"items":[{"hrid":"/items/chaotic_flail","level":3}]}
```

The endpoint merges it into whatever the cell already held, keyed on `hrid`,
**keeping the higher `level`**. Over many captures the picture converges. Max is
the honest rule here only because the guild plays ironman with no marketplace:
items are not sold, and de-levelling is rare enough to ignore.

The item set is generated from the game's own catalogue rather than written
down, so a new tier is picked up automatically. The consumer is
`guild/` Python, not a human reading the cell.

### Operating notes

- **Merging is why this script takes a lock.** Two machines writing at once used
  to be harmless. With a merge, both read the cell, both union their own view,
  and the second write discards the first's contribution — permanently. A write
  that cannot get the lock is answered `ok:false` with a `busy:` error; just
  retry. Nothing is lost by a skipped write, because the same gear is seen again
  the next time that card is opened.
- **`mode:"replace"` is refused** while the column holds anything, since no
  single machine can rebuild the union. Export the column first, then re-send
  with `discardGearHistory:true` if you genuinely mean to discard it. The
  userscript never sends that flag.
- **A cell that will not parse is left exactly as it is** and counted in the
  response's `gearSkipped`. That is deliberate: it may have been hand-edited, or
  it may reveal a bug in the writer, and either way it can hold months of
  captures. The trade-off is that such a cell never self-heals — **clear it by
  hand** and the next write starts a fresh union.
- **Blank is not empty.** A member with `hideWearableItems` set sends a blank
  cell, which contributes nothing and erases nothing. `{"items":[]}` means "we
  looked and they wore none of it", which is a different and weaker claim.
- **Refined and base items both persist.** Refining consumes the base item, so a
  member who has refined will show both hrids for ever — truthfully, "owned the
  base, now refined". `itemDetailMap[hrid].baseItemHrids` (38 pairs in the
  catalogue) lets the consumer collapse the pair; do not count them as two.
- **The response reports `gearMerged` and `gearSkipped`** alongside
  `updated`/`appended`. A non-zero `gearSkipped` on a tab nobody has hand-edited
  means a writer bug — investigate rather than ignore.

## Safety notes

- **Allowlist.** `ALLOWED_TABS` here contains **only profile tabs**. The sign-up
  tabs are deliberately absent, so a 101-column profile block can never bury the
  sheet `guild/src/signup.py` parses.
- **Shared secret.** The `/exec` URL is world-reachable. Treat the secret like a
  password; rotate by changing it in both places and re-deploying. Keep it
  distinct from the sign-up script's so one leak does not expose both.
- **The gear union is the one irreplaceable thing on the tab.** Every other
  column can be rebuilt by re-sending from `guild-profile-store`, which keeps
  each profile verbatim. The union cannot: it is the pooled history of several
  machines. Guard `mode:"replace"` accordingly.
- **Blanks vs zeros.** `null` becomes an empty cell, never `0` — a withheld tool
  (a member with `hideWearableItems` set) or an absent `famePoints` must not read
  as a real score. A genuine `0`, such as an unpurchased shrine, is written as a
  literal `0`.
