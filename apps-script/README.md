# Guild sign-up write endpoint (Apps Script Web App)

The **write** counterpart to the read-only CSV pipeline. It lets the in-game
Tampermonkey module push the guild roster + each member's trial sign-up straight
into a tab of the guild sheet — without any service-account keys and without
changing the sheet's public "anyone with the link can view" sharing.

```
Game tab (Tampermonkey: guild-signup-sync)
   │  reads guild_characters_updated off the WebSocket
   │  builds { tab, header:["User", …drawn skills, …combat], rows:[[name, TRUE/FALSE …], …] }
   │  tab is chosen from the ROSTER's own guild id (guildCharacterMap[*].guildID)
   ▼  POST (GM_xmlhttpRequest, shared-secret auth)
script.google.com/macros/s/<id>/exec   ← Code.gs, runs as the sheet OWNER
   ▼  writes (only tabs named in TAB_FORMAT, and only in that tab's format)
"chikenz-test" (safety default)  →  per-guild tab by id:
      Survey Corps        → "SC Trial Signup"
      Lactose lntolerance → "LI Trial Signup"   (guild id 240)
```

The same module optionally sends a **second, unrelated block**: the guild's
**building & shrine levels**, bound for its own per-guild tab.

```
   │  reads guildBuildingLevelMap off guild_updated / init_character_data
   │  builds { tab, header:["Building","Hrid","Kind","Level","Guild Id","Captured At"], rows:[…28…] }
   ▼
      Survey Corps        → "SC Buildings"
      Lactose lntolerance → "LI Buildings"
```

`TAB_FORMAT` records which **block format** each tab holds — `signup`
(`header[0] === "User"`) or `buildings` (`header[0] === "Building"`) — and a
block is written **only** to a tab of its own format. That is the interlock that
matters: a levels block landing on a sign-up tab would wipe the roster the
Python reader parses. Either way round it is refused as a `format mismatch`.

The module lives in the sibling repo:
`~/pie/farm/cowstuff/tampermonkey/src/modules/guild-signup-sync/index.js`.

## One-time setup

1. **Create the tabs by hand.** The script refuses any tab not named in
   `TAB_FORMAT`, and **never creates one**. In the guild spreadsheet you need:
   - **`SC Trial Signup`**, **`LI Trial Signup`** — each guild's real sign-up tab
   - **`chikenz-test`** — a duplicate of one of them, the sign-up test tab
   - **`SC Buildings`**, **`LI Buildings`** — each guild's building/shrine levels.
     Add these two as **empty** tabs; the first write fills them.

   There is deliberately **no buildings test tab**. A levels block cannot reach a
   sign-up tab (format mismatch), so it has nothing to clobber — once
   **Also sync building/shrine levels** is on and **Force Buildings tab
   (testing)** is left empty, writes go straight to the per-guild tab.
2. **Add the script.** Spreadsheet → **Extensions → Apps Script**. Paste
   `Code.gs` in, replacing the default file.
3. **Set the secret.** Change `SHARED_SECRET` to a long random string. Until you
   do, every request is refused (a deliberate interlock).
4. **Deploy as a web app.** **Deploy → New deployment → Web app**:
   - **Execute as:** *Me* (the sheet owner)
   - **Who has access:** *Anyone*

   Authorise when prompted, then copy the **deployment URL** (ends in `/exec`).
5. **Configure the module** (in-game, MWIX command palette → *Guild sign-up
   sync* → settings):
   - **Apps Script /exec URL** → the URL from step 4
   - **Shared secret** → the exact string from step 3
   - **Force tab (testing)** → leave as `chikenz-test` for now
   - **Guild id → tab map** → leave the default (`4 = SC Trial Signup`,
     `240 = LI Trial Signup`). The tab is chosen from the roster's own guild id
     (logged on every sync); add a line for any further guild.
   - **Also sync building/shrine levels** → off for now; turn it on once the
     two Buildings tabs exist. **Guild id → Buildings tab map** defaults to
     `4 = SC Buildings`, `240 = LI Buildings`, and **Force Buildings tab
     (testing)** is empty by default, so levels route by guild immediately.

## Verify (before touching the real tab)

- **Run the tests** (no dependencies; stubs `SpreadsheetApp`, so nothing touches
  the live sheet):
  ```bash
  cd ~/pie/farm/guild && node --test apps-script/Code.test.js
  ```
- **Health check:** open the `/exec` URL in a browser. You should see
  `{"ok":true,"service":"guild-signup-sync","allowedTabs":[…],"tabFormats":{…}}`.
- **Dry run:** enable the module, turn on **Dry run** in settings, open
  Guild ▸ Members, then click the module's **panel** button in the palette. It
  logs the rows it *would* write to the console — no write happens.
- **Real test write:** turn Dry run off, click the panel button. Watch the toast
  (`✓ Wrote N members to 'chikenz-test'`), then eyeball the tab.
- **Round-trip through the reader** (proves the guild pipeline can parse what we
  wrote):
  ```bash
  cd ~/pie/farm/guild
  uv run python -c "from src.signup import fetch_signup_csv, parse_signup; \
    print(parse_signup(fetch_signup_csv('chikenz-test')))"
  ```
  This should print `{member_name: {ticked skills}}` matching the game.

## Going live

Only after the round-trip looks right: **clear** the module's **Force tab
(testing)** setting. Writes then route by the **roster's own guild id** via the
**Guild id → tab map** (default `4 → SC Trial Signup`, `240 → LI Trial Signup`).
Both real tabs are already in `TAB_FORMAT`, so there is no code change and no
re-deploy. A roster from an **unmapped** guild is refused — so one guild can
never overwrite another's tab.

## Re-deploying after an edit

Editing `Code.gs` does **not** change the live `/exec` behaviour until you
**Deploy → Manage deployments → (edit) → Version: New version → Deploy**. The
`/exec` URL stays the same across versions.

## Safety notes

- **Allowlist.** `TAB_FORMAT` is the last defence against a wrong tab name
  clobbering member data — and, because it records each tab's block *format*, a
  wrong-*payload* write too. Add tabs deliberately, with the right format.
- **Shared secret.** The `/exec` URL is world-reachable. The secret is what stops
  a stranger POSTing junk. Treat it like a password; rotate by changing it in
  both places and re-deploying.
- **Overwrite semantics.** The script clears the previously-used region of the
  target tab — up to the wider of the old and new width, capped at column **30**
  (anything further right is left untouched) — and rewrites the fresh block from
  `A1`, so no stale member (or stale column from a wider previous week) lingers.
- **Boolean cells.** Ticks are written as native booleans, which display as
  `TRUE`/`FALSE` and export to CSV as `TRUE`/`FALSE` — exactly what
  `reader._to_bool` accepts. This applies to `signup` blocks only; a `buildings`
  block writes numbers as numbers (so `Level` is a real integer cell) and
  everything else as text.
- **Empty maps are refused.** The module will not write a building block for a
  guild reporting an empty `guildBuildingLevelMap`, rather than zero the tab.
