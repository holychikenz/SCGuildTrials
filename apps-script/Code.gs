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
 *     'signup'     col 0 = "User",     then one boolean tick per trial column
 *     'buildings'  col 0 = "Building", then Hrid, Kind, Level, Guild Id, Captured At
 *     'combat'     col 0 = "Member",   then Trial Hrid, Team, Role, Slot, Guild Id, Generated At
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
//   "SC …" — Survey Corps (guild id 4);  "LI …" — Lactose lntolerance (guild id 240)
var TAB_FORMAT = {
  'chikenz-test':    'signup',
  'SC Trial Signup': 'signup',
  'LI Trial Signup': 'signup',
  'SC Buildings':    'buildings',
  'LI Buildings':    'buildings',
  'SC Combat Teams': 'combat',
  'LI Combat Teams': 'combat'
};
var ALLOWED_TABS = Object.keys(TAB_FORMAT);

// The layout is header-driven and width-agnostic: the module sends "User" plus
// however many tick columns this week's draw needs (compact = 4 skills + 2
// combat = 7 columns; a full-skills layout = 13). A buildings block is a fixed
// 6, a combat block a fixed 7 — but neither width is asserted here, because the
// PYTHON readers guard their own headers cell by cell and a width check here
// would be a second, drifting copy of that contract. The only hard invariant is
// that col 0 names the format ("User", "Building" or "Member"); this floor just
// rejects an obviously-truncated payload.
var MIN_COLS = 3;

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
      return json_({ ok: false, error: 'bad header: col 0 must be "User" (sign-ups), "Building" (levels) or "Member" (combat teams)' });
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
    var ssId = String(body.spreadsheetId || SPREADSHEET_ID);
    var ss = SpreadsheetApp.openById(ssId);
    var sh = ss.getSheetByName(tab);
    if (!sh) {
      return json_({ ok: false, error: 'tab not found: "' + tab + '" — create it first' });
    }

    // --- Build the block: header (text) + rows (tick cells -> booleans) -----
    // Row 0 is the header verbatim (User + skill names + combat-trial names).
    var out = [header.slice()];
    for (var r = 0; r < rows.length; r++) {
      var src = rows[r];
      var line = [String(src[0])];               // User / Building / Member name (text)
      for (var c = 1; c < nCols; c++) {
        line.push(format === 'signup' ? truthy_(src[c]) : cell_(src[c]));
      }
      out.push(line);
    }

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

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
