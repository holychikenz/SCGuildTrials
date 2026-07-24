/**
 * GUILD TRIALS — sign-up write endpoint (Google Apps Script Web App)
 * ---------------------------------------------------------------------------
 * The counterpart to the Tampermonkey module `guild-signup-sync`
 * (~/pie/cowstuff/tampermonkey/src/modules/guild-signup-sync/index.js).
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
 * only writes tabs on the ALLOWED_TABS allowlist below.
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
 *   5. Create the test tab "chikenz-test" (a duplicate of a sign-up tab), and
 *      make sure each guild's real sign-up tab in ALLOWED_TABS already exists
 *      ("SC Trial Signup", "LI Trial Signup"). doPost never CREATES a tab — it
 *      only writes an existing one. Only tabs in ALLOWED_TABS can ever be written.
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

// Only these tabs may be written. Keep the test tab first; each guild's real
// sign-up tab is listed alongside. This is the last line of defence against a
// fat-fingered (or wrong-guild) tab name clobbering member data.
//   "SC Trial Signup" — Survey Corps
//   "LI Trial Signup" — Lactose lntolerance (guild id 240)
var ALLOWED_TABS = ['chikenz-test', 'SC Trial Signup', 'LI Trial Signup'];

// The layout is header-driven and width-agnostic: the module sends "User" plus
// however many tick columns this week's draw needs (compact = 4 skills + 2
// combat = 7 columns; a full-skills layout = 13). The only hard invariants are
// col 0 = "User" and a boolean-coercible tick in every column after it. This
// floor just rejects an obviously-truncated payload.
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
    if (!Array.isArray(header) || header.length < MIN_COLS ||
        String(header[0]) !== 'User') {
      return json_({ ok: false, error: 'bad header: need ["User", ...>=10 tick columns]' });
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
      var line = [String(src[0])];               // User name (text)
      for (var c = 1; c < nCols; c++) {
        line.push(truthy_(src[c]));               // native boolean (checkbox-friendly)
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
  return json_({ ok: true, service: 'guild-signup-sync', allowedTabs: ALLOWED_TABS });
}

// TRUE (string, any case) or boolean true → true; everything else → false.
// Mirrors guild/src/reader.py _to_bool so what we write reads back identically.
function truthy_(v) {
  if (v === true) return true;
  if (typeof v === 'string') return v.trim().toUpperCase() === 'TRUE';
  return !!v;
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
