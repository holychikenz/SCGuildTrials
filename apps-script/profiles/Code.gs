/**
 * GUILD PROFILES — member roster write endpoint (Google Apps Script Web App)
 * ---------------------------------------------------------------------------
 * The counterpart to the Tampermonkey modules `guild-profile-store` /
 * `guild-profile-sheet`
 * (~/pie/cowstuff/tampermonkey/src/modules/guild-profile-sheet/index.js).
 *
 * INDEPENDENT OF THE SIGN-UP ENDPOINT, deliberately. Sign-ups and profile
 * lookups are unrelated jobs with unrelated payloads, so they get separate
 * script projects, separate deployments, and separate secrets:
 *
 *     ../Code.gs           sign-ups   → "SC Trial Signup"  (its own /exec URL)
 *     this file            profiles   → "SC Roster"        (its own /exec URL)
 *
 * The benefit is blast radius. Editing this file cannot break the live sign-up
 * pipeline, and needs no re-deploy of it. Neither script has any notion of the
 * other, and neither needs an `action` discriminator.
 *
 * They also cannot be confused for one another even if you paste the wrong URL
 * into the wrong module's settings: a sign-up payload has no `characterId`
 * column and is refused here, while a profile payload's header does not start
 * with "User" and is refused there. The contracts guard themselves.
 *
 * Like the sign-up script, this runs as the sheet OWNER — no service-account
 * keys, and no change to the sheet's public "anyone with the link can view"
 * sharing.
 *
 * ── The data ───────────────────────────────────────────────────────────────
 * The game pushes one `profile_shared` message per profile card opened, which
 * carries that character's whole public record — every skill with exact XP,
 * equipped gear with enhancement levels, house rooms, shrine buff purchases,
 * abilities, achievements, and the various point totals. The userscript
 * archives each one verbatim, then flattens ONE guild's worth into a wide,
 * header-driven block: one row per character, ~101 columns.
 *
 * ── UPSERT, not overwrite. This is the important part. ─────────────────────
 * Profile cards are opened ONE AT A TIME, over days. Any given write may carry
 * three members when the tab already holds forty. So rows are matched on
 * `characterId` and updated in place, unknown ids are appended, and members
 * ABSENT FROM THE PAYLOAD ARE LEFT UNTOUCHED.
 *
 * This is the opposite of the sign-up script, and correctly so: there, one
 * `guild_characters_updated` message carries the WHOLE roster, so clearing and
 * rewriting is safe. Doing that here would delete the thirty-seven members you
 * happened not to look at this session. `mode:"replace"` exists for a
 * deliberate full refresh.
 *
 * We key on the numeric character id, never the name: names change (the game
 * carries a `previousName` field), and a renamed member would otherwise be
 * appended a second time instead of updated.
 *
 * ── One-time setup ─────────────────────────────────────────────────────────
 *   1. Create a NEW Apps Script project — script.google.com → New project.
 *      (Standalone, NOT bound to the spreadsheet: this file opens the sheet by
 *      id, and a separate project is what keeps the two deployments apart.)
 *   2. Paste this file in as `Code.gs`.
 *   3. Set SHARED_SECRET below to a long random string, DIFFERENT from the
 *      sign-up script's. The module's "Shared secret" setting must match.
 *   4. Deploy ▸ New deployment ▸ type "Web app":
 *         Execute as:      Me (the sheet owner)
 *         Who has access:  Anyone
 *      Copy the deployment URL (ends in /exec) into the Guild Profile Sheet
 *      module's "Apps Script /exec URL" setting.
 *   5. Create each guild's roster tab ("SC Roster", "LI Roster"). doPost never
 *      CREATES a tab. It does WIDEN one — a new tab is 26 columns wide and a
 *      profile block is ~101.
 *
 * Re-deploy (Deploy ▸ Manage deployments ▸ edit ▸ new version) after any edit,
 * or the live /exec URL keeps serving the old code.
 *
 * Tests: `node --test apps-script/profiles/Code.test.js` — stubs SpreadsheetApp
 * so the upsert logic can be checked without touching the live sheet.
 * ---------------------------------------------------------------------------
 */

// The guild spreadsheet (guild/src/config.py SHEET_ID) — the SAME document as
// the sign-up script writes, but a different tab within it. Pinned by id rather
// than getActiveSpreadsheet() so this can live in its own standalone project.
var SPREADSHEET_ID = '1b5_zID6K4WRaFXnBMJijSEXr_4l2gi40eFKxuvRJQAE';

// MUST match the module's "Shared secret" setting, and should NOT be the same
// string as the sign-up script's — separate deployments, separate credentials.
// The /exec URL is world-reachable ("Anyone"); this is what stops a stranger
// POSTing junk. Replace the placeholder or every request is refused.
var SHARED_SECRET = 'PASTE_A_LONG_RANDOM_SECRET_HERE';

// Only these tabs may be written. This is the last line of defence against a
// fat-fingered (or wrong-guild) tab name clobbering member data. The sign-up
// tabs are deliberately NOT here.
//
// Naming mirrors the sign-up tabs — "SC Trial Signup" / "LI Trial Signup" for
// sign-ups, "SC Roster" / "LI Roster" for profiles — so the guild is obvious at
// a glance and the two jobs stay visually distinct in the tab bar.
//   "SC Roster" — Survey Corps          (guild id 4)
//   "LI Roster" — Lactose lntolerance   (guild id 240)
//
// There is no scratch/test tab here, unlike the sign-up script's "chikenz-test".
// That one earns its place because a sign-up write CLEARS the block and rewrites
// it, over a tab the Python pipeline parses. This endpoint only ever upserts, so
// a mistaken write adds or updates rows and cannot wipe the tab; the module's
// dry-run is the rehearsal mechanism instead.
var ALLOWED_TABS = ['SC Roster', 'LI Roster'];

// Rows are upserted on this column. See the header comment for why it is the
// numeric id and not the name.
var KEY_COLUMN = 'characterId';

// A profile block is wide; these bound an obviously-wrong payload.
var MAX_COLS = 300;
var MIN_COLS = 5;

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

    // --- Target tab (allowlisted) -------------------------------------------
    var tab = String(body.tab || '');
    if (ALLOWED_TABS.indexOf(tab) === -1) {
      return json_({ ok: false, error: 'tab not allowed: "' + tab + '"' });
    }

    // --- Shape guards -------------------------------------------------------
    var header = body.header;
    if (!Array.isArray(header) || header.length < MIN_COLS) {
      return json_({ ok: false, error: 'bad header: need at least ' + MIN_COLS + ' columns' });
    }
    if (header.length > MAX_COLS) {
      return json_({ ok: false, error: 'header too wide: ' + header.length + ' > ' + MAX_COLS });
    }
    var nCols = header.length;

    // Also the guard that catches a SIGN-UP payload arriving here by mistake
    // (the wrong /exec URL pasted into the wrong module's settings): its header
    // is ["User", …] and carries no characterId.
    var keyIdx = -1;
    for (var k = 0; k < nCols; k++) {
      if (String(header[k]) === KEY_COLUMN) { keyIdx = k; break; }
    }
    if (keyIdx === -1) {
      return json_({ ok: false, error: 'header must contain a "' + KEY_COLUMN +
        '" column (is this a sign-up payload sent to the profiles endpoint?)' });
    }

    var rows = body.rows;
    if (!Array.isArray(rows)) {
      return json_({ ok: false, error: 'rows must be an array' });
    }
    for (var i = 0; i < rows.length; i++) {
      if (!Array.isArray(rows[i]) || rows[i].length !== nCols) {
        return json_({ ok: false, error: 'row ' + i + ' width ' +
          ((rows[i] || []).length) + ' != header ' + nCols });
      }
      if (String(rows[i][keyIdx] === undefined ? '' : rows[i][keyIdx]) === '') {
        return json_({ ok: false, error: 'row ' + i + ' has an empty ' + KEY_COLUMN });
      }
    }

    var mode = String(body.mode || 'upsert');
    if (mode !== 'upsert' && mode !== 'replace') {
      return json_({ ok: false, error: 'mode must be "upsert" or "replace"' });
    }

    // --- Open sheet (do NOT create — the tab must already exist) ------------
    var ssId = String(body.spreadsheetId || SPREADSHEET_ID);
    var ss = SpreadsheetApp.openById(ssId);
    var sh = ss.getSheetByName(tab);
    if (!sh) {
      return json_({ ok: false, error: 'tab not found: "' + tab + '" — create it first' });
    }

    // A fresh tab is 26 columns wide and a profile block is ~101. Widen before
    // writing, or setValues throws on a range beyond the sheet.
    if (sh.getMaxColumns() < nCols) {
      sh.insertColumnsAfter(sh.getMaxColumns(), nCols - sh.getMaxColumns());
    }

    var out = [];
    var updated = 0, appended = 0, replaced = false;

    var lastRow = sh.getLastRow();
    var existingHeader = lastRow >= 1 ? sh.getRange(1, 1, 1, nCols).getValues()[0] : [];

    if (mode === 'replace' || lastRow < 1 || isBlankRow_(existingHeader)) {
      // Fresh tab, or a deliberate full refresh.
      if (mode === 'replace' && lastRow >= 1) {
        var clearCols = Math.min(Math.max(nCols, sh.getLastColumn(), 1),
                                 sh.getMaxColumns(), MAX_COLS);
        sh.getRange(1, 1, Math.max(lastRow, 1), clearCols).clearContent();
        replaced = true;
      }
      for (var r0 = 0; r0 < rows.length; r0++) out.push(normaliseRow_(rows[r0], nCols));
      appended = out.length;
    } else {
      // Upsert. The existing header must agree, or column meanings shift
      // silently — toggling the module's "exact XP" setting inserts a column
      // beside every skill, which would write levels into XP cells for every
      // row already on the tab.
      var mismatch = headerMismatch_(existingHeader, header);
      if (mismatch) {
        return json_({
          ok: false,
          error: 'header mismatch at column ' + (mismatch.at + 1) + ': sheet has "' +
                 mismatch.sheet + '", payload has "' + mismatch.payload +
                 '". Re-send with mode:"replace" to rewrite the tab, or restore the ' +
                 'previous column settings.'
        });
      }

      // One read, one write: the block is pulled into memory, mutated, and
      // written back, so cost does not scale with the number of rows touched.
      var existing = lastRow >= 2 ? sh.getRange(2, 1, lastRow - 1, nCols).getValues() : [];
      var index = {};
      for (var x = 0; x < existing.length; x++) {
        var ek = String(existing[x][keyIdx] === undefined ? '' : existing[x][keyIdx]);
        if (ek !== '') index[ek] = x;
      }
      out = existing;
      for (var r = 0; r < rows.length; r++) {
        var row = normaliseRow_(rows[r], nCols);
        var key = String(row[keyIdx]);
        if (Object.prototype.hasOwnProperty.call(index, key)) {
          out[index[key]] = row;
          updated++;
        } else {
          index[key] = out.length;
          out.push(row);
          appended++;
        }
      }
    }

    // Grow the sheet if an append pushed past its height.
    var needRows = out.length + 1;               // + header
    if (sh.getMaxRows() < needRows) {
      sh.insertRowsAfter(sh.getMaxRows(), needRows - sh.getMaxRows());
    }

    sh.getRange(1, 1, 1, nCols).setValues([header.slice()]);
    if (out.length) sh.getRange(2, 1, out.length, nCols).setValues(out);

    return json_({
      ok: true,
      tab: tab,
      mode: mode,
      guildId: body.guildId != null ? body.guildId : null,
      guildName: body.guildName != null ? String(body.guildName) : null,
      received: rows.length,
      updated: updated,
      appended: appended,
      replaced: replaced,
      totalRows: out.length,
      columns: nCols
    });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

// A browser-openable health check. Visiting the /exec URL returns this JSON,
// which confirms the deployment is live without writing anything.
function doGet() {
  return json_({
    ok: true,
    service: 'guild-profile-sheet',
    allowedTabs: ALLOWED_TABS,
    keyColumn: KEY_COLUMN
  });
}

// Sheets cannot hold null/undefined; both become an empty cell. A blank is the
// honest rendering of "withheld" (a member hiding their gear) or "absent"
// (famePoints, which only some profiles carry) — a 0 there would read as a real
// score. Booleans stay native (they display and export as TRUE/FALSE), numbers
// stay numbers.
function normaliseRow_(src, nCols) {
  var line = [];
  for (var c = 0; c < nCols; c++) {
    var v = src[c];
    line.push((v === null || v === undefined) ? '' : v);
  }
  return line;
}

function isBlankRow_(arr) {
  for (var i = 0; i < arr.length; i++) {
    if (String(arr[i] === undefined ? '' : arr[i]) !== '') return false;
  }
  return true;
}

// Returns null when the headers agree, else the first disagreement.
function headerMismatch_(sheetHeader, payloadHeader) {
  for (var i = 0; i < payloadHeader.length; i++) {
    var a = String(sheetHeader[i] === undefined ? '' : sheetHeader[i]);
    var b = String(payloadHeader[i]);
    if (a !== b) return { at: i, sheet: a, payload: b };
  }
  return null;
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
