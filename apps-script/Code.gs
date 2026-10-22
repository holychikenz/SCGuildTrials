/**
 * GUILD TRIALS — sign-up write endpoint (Google Apps Script Web App)
 * ---------------------------------------------------------------------------
 * The counterpart to the Tampermonkey module `guild-signup-sync`
 * (~/pie/farm/cowstuff/tampermonkey/src/modules/guild-signup-sync/index.js).
 *
 * The game emits one `guild_characters_updated` WebSocket message when you open
 * Guild ▸ Members; the userscript turns it into { header, rows, tab } and POSTs
 * it here. This script writes those rows into the named tab of the guild sheet,
 * running as the sheet OWNER (so no service-account keys and no change to the
 * sheet's public "anyone with the link can view" sharing — the credential-free
 * ethos of the whole pipeline is preserved).
 *
 * MULTI-GUILD: the operator plays characters in more than one guild, and each
 * guild owns its OWN sign-up tab in this shared spreadsheet ("SC Trial Signup"
 * for Survey Corps, "LI Trial Signup" for Lactose lntolerance). The userscript
 * picks the tab from the CURRENT guild's id and sends it in `tab`; this script
 * only writes tabs on the TAB_FORMAT allowlist below.
 *
 * THREE BLOCK FORMATS, one per tab. The same module also (optionally) sends
 * the guild's BUILDING & SHRINE LEVELS — a different block entirely, bound for
 * a different tab ("SC Buildings" / "LI Buildings"). A third block arrives from
 * a different program altogether (see the note under 'combat'):
 *     'signup'     col 0 = "User",     then one boolean tick per trial column,
 *                  then an optional trailing "characterId" (a VALUE cell, not a tick)
 *     'buildings'  col 0 = "Building", then Hrid, Kind, Level, Guild Id, Captured At
 *     'combat'     col 0 = "Member",   then Trial Hrid, Team, Role, Slot, Guild Id, Generated At
 *     'building_value' col 0 = "Upgrade", then Hrid, Level, ... Payback Weeks, ... Generated At
 *                  (SCLIRoster optimizer/src/publish/buildingTab.js HEADER; written
 *                  by the same optimiser, with the same secret, as 'combat')
 *     'name_history' col 0 = "Character Id", then Name, Guild Id, First Seen, Last Seen
 *                  (guild-signup-sync; rename safety 2026-10). UPSERTED on
 *                  (Character Id, Name) under a script lock — NEVER a whole-tab
 *                  rewrite — and every cell is written as TEXT.
 * The 'combat' block is written by the OPTIMISER (~/pie/SCLIRoster, a Node CLI:
 * `report --publish-combat`) — NOT by the in-game module, which knows nothing
 * about it — and is read back by guild/src/combat.py, which hangs it on
 * trials.json so the userscript can glow a member's assigned combat tiles.
 * TAB_FORMAT records which format each allowlisted tab holds, and a block is
 * written ONLY to a tab of its own format. That is the interlock that matters:
 * a levels block landing on a sign-up tab would wipe the roster the Python
 * reader parses, a roster on a Buildings tab would bury the levels, and a
 * combat block on either would do the same to whichever it landed on. All are
 * refused as a 'format mismatch' rather than written through.
 *
 * The sheet layout this writes MUST stay in lockstep with guild/src/config.py
 * (SKILLS) and guild/src/signup.py (parse_signup): col 0 = "User", then one
 * column per SKILLS entry holding a boolean (the reader treats only TRUE as
 * true). The 9th skill column, "Bell Farming", is the Alchemy trial (the joke).
 *
 * ── One-time setup ─────────────────────────────────────────────────────────
 *   1. Open the guild spreadsheet → Extensions → Apps Script.
 *   2. Paste this file in as `Code.gs`.
 *   3. Set SHARED_SECRET below to a long random string (KEEP IT SECRET). The
 *      module's "Shared secret" setting must match it exactly.
 *   4. Deploy ▸ New deployment ▸ type "Web app":
 *         Execute as:      Me (the sheet owner)
 *         Who has access:  Anyone
 *      Copy the deployment URL (ends in /exec) into the module's
 *      "Apps Script /exec URL" setting.
 *   5. Create the tabs BY HAND. doPost never CREATES a tab — it only writes an
 *      existing one, and only one named in TAB_FORMAT. You need:
 *         "chikenz-test"     the sign-up test tab (a duplicate of a sign-up tab)
 *         "SC Trial Signup"  \ each guild's real sign-up tab
 *         "LI Trial Signup"  /
 *         "SC Buildings"     \ each guild's building/shrine levels — empty is
 *         "LI Buildings"     / fine; the first write fills them
 *         "SC Combat Teams"  \ each guild's optimiser-published combat teams —
 *         "LI Combat Teams"  / NEW, and empty is fine; the first optimiser
 *                              publish fills them. MACHINE-OWNED: nobody types
 *                              in them; every publish rewrites them from A1.
 *         "SC Name History"  \ every (characterId, name) pair each guild's sync
 *         "LI Name History"  / has seen — empty is fine; the first post writes the
 *                              header. Upserted, never rewritten.
 *      There is deliberately NO buildings or combat test tab: neither block can
 *      reach a sign-up tab (format mismatch), so neither has anything to
 *      clobber, and the first write of each goes straight to its per-guild tab.
 *      For the levels block, enable the
 *      module's "Also sync building/shrine levels" and leave "Force Buildings
 *      tab (testing)" EMPTY.
 *
 * Re-deploy (Deploy ▸ Manage deployments ▸ edit ▸ new version) after any edit,
 * or the live /exec URL keeps serving the old code.
 * ---------------------------------------------------------------------------
 */

// The guild spreadsheet (guild/src/config.py SHEET_ID). A bound script could use
// getActiveSpreadsheet(), but pinning the id is explicit and fails loudly.
var SPREADSHEET_ID = '1b5_zID6K4WRaFXnBMJijSEXr_4l2gi40eFKxuvRJQAE';

// MUST match the module's "Shared secret" setting. Blocks anonymous vandalism —
// the /exec URL is world-reachable ("Anyone"). Replace the placeholder or every
// request is refused (a deliberate safety interlock).
var SHARED_SECRET = 'PASTE_A_LONG_RANDOM_SECRET_HERE';

// Which BLOCK FORMAT each allowlisted tab holds. A payload is written ONLY to a
// tab of its own format, so a buildings block can never land on a sign-up tab
// (which would wipe the roster) nor a roster on a buildings tab. This map is the
// allowlist: doPost still never CREATES a tab — every name here must exist.
//   'signup'    header[0] = "User"      roster + trial sign-ups (guild-signup-sync)
//   'buildings' header[0] = "Building"  guild building / shrine levels
//   'combat'    header[0] = "Member"    the optimiser's combat teams (SCLIRoster)
//   'building_value' header[0] = "Upgrade"  the optimiser's combat building value
//   'name_history' header[0] = "Character Id"  (id, name) pairs ever seen (upsert)
//   "SC …" — Survey Corps (guild id 4);  "LI …" — Lactose lntolerance (guild id 240)
var TAB_FORMAT = {
  'chikenz-test':    'signup',
  'SC Trial Signup': 'signup',
  'LI Trial Signup': 'signup',
  'SC Buildings':    'buildings',
  'LI Buildings':    'buildings',
  'SC Combat Teams': 'combat',
  'LI Combat Teams': 'combat',
  'SC Building Value': 'building_value',
  'LI Building Value': 'building_value',
  'SC Name History': 'name_history',
  'LI Name History': 'name_history'
};
var ALLOWED_TABS = Object.keys(TAB_FORMAT);

// The layout is header-driven and width-agnostic: the module sends "User" plus
// however many tick columns this week's draw needs (compact = 4 skills + 2
// combat = 7 columns; a full-skills layout = 13). A buildings block is a fixed
// 6, a combat block a fixed 7 — but neither width is asserted here, because the
// PYTHON readers guard their own headers cell by cell and a width check here
// would be a second, drifting copy of that contract. The only hard invariant is
// that col 0 names the format ("User", "Building", "Member", "Upgrade" or
// "Character Id"); this floor just rejects an obviously-truncated payload. The one
// exception is 'name_history', whose five cells ARE checked here (upsertNameHistory_),
// because it merges into the tab rather than rewriting it.
var MIN_COLS = 3;

// The sign-up block's optional trailing id column (rename safety, 2026-10). The
// header text is EXACT (case-sensitive) per the cross-repo contract: a cell under
// it is the member's numeric game characterId, written as a VALUE via cell_, never
// coerced by truthy_ (which would turn every id into TRUE). Every other sign-up
// cell keeps its boolean coercion.
var SIGNUP_ID_HEADER = 'characterId';

// The Name History block (rename safety, 2026-10): exactly these five cells, in this
// order, on the payload AND on the tab. guild/src/config.py NAME_HISTORY_HEADER and
// SCLIRoster's nameHistory.js verify the same row when reading it back via gviz.
var NAME_HISTORY_HEADER = ['Character Id', 'Name', 'Guild Id', 'First Seen', 'Last Seen'];
var LOCK_WAIT_MS = 30000;

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return json_({ ok: false, error: 'no request body' });
    }
    var body = JSON.parse(e.postData.contents);

    // --- Auth ---------------------------------------------------------------
    if (SHARED_SECRET === 'PASTE_A_LONG_RANDOM_SECRET_HERE') {
      return json_({ ok: false, error: 'server not configured: set SHARED_SECRET' });
    }
    if (String(body.secret || '') !== SHARED_SECRET) {
      return json_({ ok: false, error: 'unauthorised' });
    }

    // --- Target tab (allowlisted) ------------------------------------------
    var tab = String(body.tab || '');
    if (ALLOWED_TABS.indexOf(tab) === -1) {
      return json_({ ok: false, error: 'tab not allowed: ' + tab });
    }

    // --- Shape guards -------------------------------------------------------
    var header = body.header;
    if (!Array.isArray(header) || header.length < MIN_COLS) {
      return json_({ ok: false, error: 'bad header: need at least ' + MIN_COLS + ' columns' });
    }
    var format = formatOf_(header);
    if (!format) {
      return json_({ ok: false, error: 'bad header: col 0 must be "User" (sign-ups), "Building" (levels), "Member" (combat teams), "Upgrade" (building value) or "Character Id" (name history)' });
    }
    if (TAB_FORMAT[tab] !== format) {
      return json_({ ok: false, error: 'format mismatch: a ' + format + ' block may not be written to "' + tab + '" (' + TAB_FORMAT[tab] + ' tab)' });
    }
    var nCols = header.length;   // User + 10 skills + any extra (combat) columns
    var rows = body.rows;
    if (!Array.isArray(rows)) {
      return json_({ ok: false, error: 'rows must be an array' });
    }
    for (var i = 0; i < rows.length; i++) {
      if (!Array.isArray(rows[i]) || rows[i].length !== nCols) {
        return json_({ ok: false, error: 'row ' + i + ' width ' + (rows[i] || []).length + ' != header ' + nCols });
      }
    }

    // --- Open sheet (do NOT create — the tab must already exist) ------------
    // Always SPREADSHEET_ID: this runs as the sheet OWNER, so honouring a
    // caller-supplied id would let anyone with the secret write any owner sheet.
    var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    var sh = ss.getSheetByName(tab);
    if (!sh) {
      return json_({ ok: false, error: 'tab not found: "' + tab + '" — create it first' });
    }

    // The one block that is MERGED rather than rewritten.
    if (format === 'name_history') return json_(upsertNameHistory_(sh, tab, header, rows));

    // --- Build the block: header (text) + rows (tick cells -> booleans) -----
    // Row 0 is the header verbatim (User + skill names + combat-trial names).
    var out = [header.slice()];
    var idCol = -1;                                // sign-up characterId column, if any
    if (format === 'signup') {
      for (var h = 1; h < nCols; h++) {
        if (String(header[h]) === SIGNUP_ID_HEADER) { idCol = h; break; }
      }
    }
    for (var r = 0; r < rows.length; r++) {
      var src = rows[r];
      var line = [String(src[0])];               // User / Building / Member name (text)
      for (var c = 1; c < nCols; c++) {
        line.push(format === 'signup' && c !== idCol ? truthy_(src[c]) : cell_(src[c]));
      }
      out.push(line);
    }

    // Under the script lock, like upsertNameHistory_: two concurrent posts must not
    // interleave their clear and write (one's clear landing after the other's rows).
    var lock = LockService.getScriptLock();
    if (!lock.tryLock(LOCK_WAIT_MS)) {
      return json_({ ok: false, error: 'busy: another write holds the lock; retry in a moment' });
    }
    try {
      var newRows = out.length;                      // header + members
      var maxRows = sh.getMaxRows();
      var clearRows = Math.min(Math.max(sh.getLastRow(), newRows, 1), maxRows);

      // Overwrite semantics. Clear the whole PREVIOUSLY-USED region (up to the old
      // last column, capped at 30 as a runaway guard) so that when the layout
      // SHRINKS week-to-week — e.g. from a 13-column full-skills write down to a
      // 7-column compact draw — no stale columns linger to the right. Then write
      // the fresh block from A1. Anything beyond column 30 is left untouched.
      var maxCols = sh.getMaxColumns();
      var clearCols = Math.min(Math.max(nCols, sh.getLastColumn(), 1), maxCols, 30);
      sh.getRange(1, 1, clearRows, clearCols).clearContent();
      sh.getRange(1, 1, newRows, nCols).setValues(out);

      SpreadsheetApp.flush();                      // commit BEFORE the release
    } finally {
      lock.releaseLock();
    }

    return json_({
      ok: true,
      tab: tab,
      format: format,
      wroteRows: rows.length,
      columns: nCols,
      clearedRows: clearRows,
      clearedCols: clearCols
    });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

// A browser-openable health check. Visiting the /exec URL returns this JSON,
// which confirms the deployment is live without writing anything.
function doGet() {
  return json_({ ok: true, service: 'guild-signup-sync', allowedTabs: ALLOWED_TABS, tabFormats: TAB_FORMAT });
}

// TRUE (string, any case) or boolean true → true; everything else → false.
// Mirrors guild/src/reader.py _to_bool so what we write reads back identically.
function truthy_(v) {
  if (v === true) return true;
  if (typeof v === 'string') return v.trim().toUpperCase() === 'TRUE';
  return !!v;
}

// "User" → sign-up block, "Building" → levels block, "Member" → combat teams,
// anything else → refused. Col 0 is the whole sentinel: it is the one cell every
// writer of a given block agrees on, and it is what guild/src/config.py's
// *_SENTINEL_HEADERS check first when reading the tab back.
function formatOf_(header) {
  var h0 = String(header[0]);
  if (h0 === 'User') return 'signup';
  if (h0 === 'Building') return 'buildings';
  if (h0 === 'Member') return 'combat';
  if (h0 === 'Upgrade') return 'building_value';
  if (h0 === 'Character Id') return 'name_history';
  return null;
}

// Non-sign-up block cells (levels, combat teams): numbers stay numbers, so
// Level and Guild Id are real numeric cells; null/undefined become blank, and
// everything else is written as text.
function cell_(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') return v;
  return String(v);
}

// UPSERT on (Character Id, Name) — NEVER a whole-tab rewrite. For an existing key,
// First Seen = min of the non-empty values and Last Seen = max (ISO-8601 UTC strings
// compare lexically); Guild Id takes the new value when non-empty; "" never
// overwrites a timestamp. A new key is appended. Rows with an empty or non-numeric
// id, or an empty name, are skipped and counted in `rejected`. Every cell is written
// as TEXT ('@', set BEFORE the values) so Sheets never date-parses a timestamp or
// numberifies an id. A script lock stops two members' browsers syncing at once from
// losing each other's appends.
function upsertNameHistory_(sh, tab, header, rows) {
  var n = NAME_HISTORY_HEADER.length;
  if (header.length !== n) {
    return { ok: false, error: 'bad header: a name history block is exactly ' + NAME_HISTORY_HEADER.join(', ') };
  }
  for (var k = 0; k < n; k++) {
    if (String(header[k]) !== NAME_HISTORY_HEADER[k]) {
      return { ok: false, error: 'bad header: a name history block is exactly ' + NAME_HISTORY_HEADER.join(', ') };
    }
  }
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(LOCK_WAIT_MS)) {
    return { ok: false, error: 'busy: another write holds the lock; retry in a moment' };
  }
  try {
    var lastRow = sh.getLastRow();
    if (lastRow >= 1) {
      var existingHeader = sh.getRange(1, 1, 1, n).getValues()[0];
      var blank = existingHeader.every(function (c) { return String(c) === ''; });
      if (!blank) {
        for (var h = 0; h < n; h++) {
          if (String(existingHeader[h]) !== NAME_HISTORY_HEADER[h]) {
            return { ok: false, error: 'header mismatch at column ' + (h + 1) + ' on "' + tab +
              '": sheet has "' + existingHeader[h] + '", expected "' + NAME_HISTORY_HEADER[h] + '"' };
          }
        }
      }
    }
    var out = lastRow >= 2
      ? sh.getRange(2, 1, lastRow - 1, n).getValues().map(function (r) { return r.map(text_); })
      : [];
    var index = {};
    for (var x = 0; x < out.length; x++) {
      var ek = out[x][0] + '\u0000' + out[x][1];
      if (out[x][0] !== '' && !Object.prototype.hasOwnProperty.call(index, ek)) index[ek] = x;
    }
    var inserted = 0, updated = 0, rejected = 0;
    for (var r = 0; r < rows.length; r++) {
      var id = text_(rows[r][0]), name = text_(rows[r][1]);
      if (!/^\d+$/.test(id) || name === '') { rejected++; continue; }
      var guild = text_(rows[r][2]), first = text_(rows[r][3]), last = text_(rows[r][4]);
      var key = id + '\u0000' + name;
      if (Object.prototype.hasOwnProperty.call(index, key)) {
        var row = out[index[key]];
        if (guild !== '') row[2] = guild;
        row[3] = minNonEmpty_(row[3], first);
        row[4] = maxNonEmpty_(row[4], last);
        updated++;
      } else {
        index[key] = out.length;
        out.push([id, name, guild, first, last]);
        inserted++;
      }
    }
    var need = out.length + 1;
    if (sh.getMaxRows() < need) sh.insertRowsAfter(sh.getMaxRows(), need - sh.getMaxRows());
    var range = sh.getRange(1, 1, need, n);
    range.setNumberFormat('@');                      // BEFORE setValues: text, not dates
    range.setValues([NAME_HISTORY_HEADER.slice()].concat(out));
    // Commit the pending writes WHILE the lock is held: Apps Script batches them, so
    // a release first lets a concurrent upsert read the tab before this lands.
    SpreadsheetApp.flush();
    return { ok: true, tab: tab, format: 'name_history', received: rows.length,
             inserted: inserted, updated: updated, rejected: rejected, totalRows: out.length };
  } finally {
    lock.releaseLock();
  }
}

// A sheet value as trimmed text: null/undefined -> '', a Date (a cell Sheets parsed
// before the '@' format was set) -> ISO-8601, everything else -> String.
function text_(v) {
  if (v === null || v === undefined) return '';
  if (v instanceof Date) return v.toISOString();
  return String(v).trim();
}
function minNonEmpty_(a, b) { return a === '' ? b : (b === '' ? a : (b < a ? b : a)); }
function maxNonEmpty_(a, b) { return a === '' ? b : (b === '' ? a : (b > a ? b : a)); }

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
