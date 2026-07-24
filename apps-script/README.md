# Guild sign-up write endpoint (Apps Script Web App)

The **write** counterpart to the read-only CSV pipeline. It lets the in-game
Tampermonkey module push the guild roster + each member's trial sign-up straight
into a tab of the guild sheet — without any service-account keys and without
changing the sheet's public "anyone with the link can view" sharing.

```
Game tab (Tampermonkey: guild-signup-sync)
   │  reads guild_characters_updated off the WebSocket
   │  builds { tab, header:["User", …drawn skills, …combat], rows:[[name, TRUE/FALSE …], …] }
   │  tab is chosen from the CURRENT guild's id (multi-guild characters)
   ▼  POST (GM_xmlhttpRequest, shared-secret auth)
script.google.com/macros/s/<id>/exec   ← Code.gs, runs as the sheet OWNER
   ▼  writes (only tabs on the ALLOWED_TABS allowlist)
"chikenz-test" (safety default)  →  per-guild tab by id:
      Survey Corps        → "SC Trial Signup"
      Lactose lntolerance → "LI Trial Signup"   (guild id 240)
```

The module lives in the sibling repo:
`~/pie/cowstuff/tampermonkey/src/modules/guild-signup-sync/index.js`.

## One-time setup

1. **Create the tabs.** In the guild spreadsheet, make sure each guild's real
   sign-up tab exists (**`SC Trial Signup`**, **`LI Trial Signup`**), and
   duplicate one of them as the test tab **`chikenz-test`**. The script refuses
   any tab not in `ALLOWED_TABS`, and never creates one.
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
   - **Guild id → tab map** → leave the default (`240 = LI Trial Signup`); add
     `<Survey Corps id> = SC Trial Signup` once you know it (every sync logs the
     current guild's id + name to the console)

## Verify (before touching the real tab)

- **Health check:** open the `/exec` URL in a browser. You should see
  `{"ok":true,"service":"guild-signup-sync","allowedTabs":[…]}`.
- **Dry run:** enable the module, turn on **Dry run** in settings, open
  Guild ▸ Members, then click the module's **panel** button in the palette. It
  logs the rows it *would* write to the console — no write happens.
- **Real test write:** turn Dry run off, click the panel button. Watch the toast
  (`✓ Wrote N members to 'chikenz-test'`), then eyeball the tab.
- **Round-trip through the reader** (proves the guild pipeline can parse what we
  wrote):
  ```bash
  cd ~/pie/guild
  uv run python -c "from src.signup import fetch_signup_csv, parse_signup; \
    print(parse_signup(fetch_signup_csv('chikenz-test')))"
  ```
  This should print `{member_name: {ticked skills}}` matching the game.

## Going live

Only after the round-trip looks right: **clear** the module's **Force tab
(testing)** setting. Writes then route by the CURRENT guild's id via the
**Guild id → tab map** (`240 → LI Trial Signup`; add Survey Corps's id →
`SC Trial Signup` once the module has logged it). Both real tabs are already in
`ALLOWED_TABS`, so there is no code change and no re-deploy. A roster from an
**unmapped** guild is refused — so one guild can never overwrite another's tab.

## Re-deploying after an edit

Editing `Code.gs` does **not** change the live `/exec` behaviour until you
**Deploy → Manage deployments → (edit) → Version: New version → Deploy**. The
`/exec` URL stays the same across versions.

## Safety notes

- **Allowlist.** `ALLOWED_TABS` is the last defence against a wrong tab name
  clobbering member data. Keep the test tab first; add others deliberately.
- **Shared secret.** The `/exec` URL is world-reachable. The secret is what stops
  a stranger POSTing junk. Treat it like a password; rotate by changing it in
  both places and re-deploying.
- **Overwrite semantics.** The script clears the previously-used region of the
  target tab — up to the wider of the old and new width, capped at column **30**
  (anything further right is left untouched) — and rewrites the fresh block from
  `A1`, so no stale member (or stale column from a wider previous week) lingers.
- **Boolean cells.** Ticks are written as native booleans, which display as
  `TRUE`/`FALSE` and export to CSV as `TRUE`/`FALSE` — exactly what
  `reader._to_bool` accepts.
