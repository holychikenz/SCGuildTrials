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
 * ── ONE COLUMN IS MERGED, NOT OVERWRITTEN: `gearSeen` ──────────────────────
 * Upsert replaces a matched row wholesale, which is right for every column that
 * is a snapshot. `gearSeen` is not a snapshot: it is the UNION of every capture
 * of that member's gear, accumulated over months and across machines. Combat
 * slots rotate with whatever is being trained, so one profile card shows a
 * fraction of what somebody owns; we merge by hrid and keep the higher
 * enhancement level. See GEAR_COLUMN and mergeGear_ for the rule and its
 * reasoning, and the "gear union" section of README.md for operation.
 *
 * Three consequences worth knowing before editing this file:
 *
 *   1. THIS SCRIPT NOW TAKES A LOCK. Two machines writing at once used to be
 *      harmless — both overwrote a row with the same data. With a merge, both
 *      read the cell, both union their own view, and the second write discards
 *      the first's contribution permanently. LockService serialises the
 *      read-modify-write; a refusal is answered with a retryable `busy:`.
 *   2. `mode:"replace"` IS GUARDED. It clears out to getLastColumn(), so it
 *      reaches this column even from a narrower payload — and no single machine
 *      can rebuild the union. A replace over a populated gear column is refused
 *      unless the payload carries `discardGearHistory:true`.
 *   3. A HEADER MAY NOW GROW AT THE TAIL. headerMismatch_ tolerates a payload
 *      column whose sheet cell is blank, because the old remedy for a refusal
 *      was `mode:"replace"` — which would have destroyed the union. A SHIFT is
 *      still refused.
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
 * and LockService so the upsert and the gear merge can be checked without
 * touching the live sheet. NOTE the vm context there provides only Array,
 * String, Object, JSON, Math and Error: code in this file must not reach for
 * Number, isFinite, parseInt or Date without extending that stub.
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

// ── THE ONE COLUMN THAT IS MERGED, NOT OVERWRITTEN ─────────────────────────
// Every other cell on a row is a snapshot, and last-write-wins is correct for
// it. This one is an accumulated UNION across months and machines.
//
// Combat weapon and armour slots rotate with whatever the member is training
// this hour, so any single profile card shows a fraction of their gear. The
// userscript sends what THIS capture saw; we union it into what the cell
// already held, keyed on hrid, keeping the higher enhancement level. Over many
// captures the picture converges. Overwriting instead would throw away every
// capture but the newest, which is the entire problem this column solves.
//
// MAX-OVER-TIME IS THE HONEST RULE HERE because the guild plays ironman with no
// marketplace: items are not sold, and de-levelling is rare enough to ignore.
// In a trading economy this would over-report and a last-seen rule would be
// wanted instead.
//
// THE MERGE IS WHY THIS SCRIPT NOW TAKES A LOCK. Until this column existed, two
// machines writing at once merely overwrote a row with identical data and cost
// nothing. A merge makes the read-modify-write genuinely racy: both read the
// cell, both union their own view, and the second write silently discards the
// first's contribution — permanently. See LockService in doPost.
var GEAR_COLUMN = 'gearSeen';

// The catalogue yields 200 tracked items; these are slack to bound a runaway
// (a restructured catalogue, or a bug adding untracked hrids) rather than
// letting a cell grow into the ~50,000-character Sheets limit mid-write.
var GEAR_MAX_ITEMS = 400;
var GEAR_MAX_CHARS = 45000;

// Long enough to outlast another machine's write, short enough that a stuck
// lock surfaces as a retryable error rather than a six-minute timeout.
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

    // --- Serialise the read-modify-write ------------------------------------
    // Everything above is pure validation and needs no lock. Everything below
    // reads the block, mutates it in memory and writes it back — and with a
    // MERGE column that is no longer safe to do concurrently. Two machines
    // harvesting at once would both read the same cell, both union their own
    // view into it, and the second write would silently discard the first's
    // contribution for good.
    //
    // tryLock rather than waitLock: a refusal is a clean, retryable answer, and
    // the union is monotone, so a skipped write costs only a delay — the same
    // gear is seen again the next time that member's card is opened.
    var lock = LockService.getScriptLock();
    if (!lock.tryLock(LOCK_WAIT_MS)) {
      return json_({ ok: false,
        error: 'busy: another write holds the lock; retry in a moment' });
    }
    // NB: the body below is deliberately NOT re-indented into this try. The
    // wrapper exists only to guarantee releaseLock(); re-indenting sixty lines
    // would bury the actual change in whitespace.
    try {

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
    var gearIdx = gearColumnIndex_(header, nCols);
    var gearMerged = 0, gearSkipped = 0;

    var lastRow = sh.getLastRow();

    // `replace` clears the block wholesale — and note it clears out to
    // getLastColumn(), so it reaches the gear column even when the payload is
    // narrower than the tab. That column is the ONE thing here that cannot be
    // rebuilt from any single machine's archive: it is months of captures from
    // several of them, and guild-profile-store holds only what THIS browser
    // saw. So a replace over a populated gear column is refused unless the
    // caller states, in the payload, that it means it. The userscript never
    // sends that flag, so it can only be set deliberately by hand.
    if (mode === 'replace' && !body.discardGearHistory &&
        gearHistoryPresent_(sh, lastRow)) {
      return json_({ ok: false, error: 'refusing replace: the "' + GEAR_COLUMN +
        '" column holds accumulated gear history, which replace would destroy ' +
        'and which cannot be rebuilt from one machine. Export it first, then ' +
        're-send with discardGearHistory:true if you really mean it.' });
    }

    var existingHeader = lastRow >= 1 ? sh.getRange(1, 1, 1, nCols).getValues()[0] : [];

    if (mode === 'replace' || lastRow < 1 || isBlankRow_(existingHeader)) {
      // Fresh tab, or a deliberate full refresh.
      if (mode === 'replace' && lastRow >= 1) {
        var clearCols = Math.min(Math.max(nCols, sh.getLastColumn(), 1),
                                 sh.getMaxColumns(), MAX_COLS);
        sh.getRange(1, 1, Math.max(lastRow, 1), clearCols).clearContent();
        replaced = true;
      }
      for (var r0 = 0; r0 < rows.length; r0++) {
        var fresh = normaliseRow_(rows[r0], nCols);
        // Nothing to merge into on a fresh row, but a malformed payload must
        // still never be written through: it would poison every later merge on
        // that member, since an unparseable cell is left untouched by design.
        if (gearIdx !== -1 && parseGear_(fresh[gearIdx]) === null) {
          fresh[gearIdx] = '';
          gearSkipped++;
        }
        out.push(fresh);
      }
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
          // The one column that accumulates instead of being replaced. On the
          // very first write of a new column the sheet's cell is '', which
          // parseGear_ maps to [], so this is a clean insert with no special
          // case.
          if (gearIdx !== -1) {
            var m = mergeGear_(out[index[key]][gearIdx], row[gearIdx]);
            row[gearIdx] = m.text;
            if (m.ok) { gearMerged++; } else { gearSkipped++; }
          }
          out[index[key]] = row;
          updated++;
        } else {
          if (gearIdx !== -1 && parseGear_(row[gearIdx]) === null) {
            row[gearIdx] = '';
            gearSkipped++;
          }
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
      columns: nCols,
      gearMerged: gearMerged,
      gearSkipped: gearSkipped
    });

    } finally {
      lock.releaseLock();
    }
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

// '' → [] — a NON-CONTRIBUTION, which is what a hidden member sends and what a
// reverted userscript leaves behind. A valid payload → array of {hrid, level}.
// Anything else → null, meaning "unparseable", which the caller must treat as
// DO-NOT-TOUCH.
//
// Note the absence of isFinite/Number: Code.test.js runs this file in a vm
// context carrying only Array, String, Object, JSON, Math and Error. Hence
// self-inequality for NaN and an explicit bound for Infinity.
function parseGear_(cell) {
  var s = String(cell === null || cell === undefined ? '' : cell);
  if (s === '') return [];
  var obj;
  try { obj = JSON.parse(s); } catch (e) { return null; }
  if (!obj || typeof obj !== 'object' || !Array.isArray(obj.items)) return null;
  var out = [];
  for (var i = 0; i < obj.items.length; i++) {
    var it = obj.items[i];
    if (!it || typeof it !== 'object') return null;
    var hrid = String(it.hrid === null || it.hrid === undefined ? '' : it.hrid);
    if (hrid === '' || hrid.length > 120) return null;
    var lvl = it.level;
    if (typeof lvl !== 'number' || lvl !== lvl || lvl < 0 || lvl > 1000) return null;
    out.push({ hrid: hrid, level: lvl });
  }
  return out;
}

// Union by hrid, keeping the HIGHER enhancement level.
//
// ok:false means the merge was ABANDONED and `text` is the existing cell
// verbatim. Abandoning is non-destructive by construction, and deliberately so:
// a cell that will not parse may have been hand-edited in the spreadsheet, or
// may reveal a bug in OUR writer, and either way it can hold months of captures
// that no single machine could rebuild. Silently replacing it would destroy
// exactly the data this column exists to accumulate. The trade-off is that such
// a cell never self-heals — the response reports the count so it is visible
// rather than silent, and clearing the cell by hand starts a fresh union.
function mergeGear_(existing, incoming) {
  var keep = String(existing === null || existing === undefined ? '' : existing);
  var ex = parseGear_(existing);
  if (ex === null) return { text: keep, ok: false, reason: 'unparseable-cell' };
  var inc = parseGear_(incoming);
  if (inc === null) return { text: keep, ok: false, reason: 'unparseable-payload' };

  var byHrid = {}, i, h;
  for (i = 0; i < ex.length; i++) byHrid[ex[i].hrid] = ex[i].level;
  for (i = 0; i < inc.length; i++) {
    h = inc[i].hrid;
    byHrid[h] = Object.prototype.hasOwnProperty.call(byHrid, h)
      ? Math.max(byHrid[h], inc[i].level)
      : inc[i].level;
  }

  var hrids = Object.keys(byHrid).sort();
  if (hrids.length > GEAR_MAX_ITEMS) {
    return { text: keep, ok: false, reason: 'too-many-items' };
  }
  var items = [];
  for (i = 0; i < hrids.length; i++) items.push({ hrid: hrids[i], level: byHrid[hrids[i]] });
  var text = JSON.stringify({ items: items });
  if (text.length > GEAR_MAX_CHARS) return { text: keep, ok: false, reason: 'too-large' };
  return { text: text, ok: true };
}

function gearColumnIndex_(header, nCols) {
  for (var i = 0; i < nCols; i++) if (String(header[i]) === GEAR_COLUMN) return i;
  return -1;
}

// Does the TAB already hold accumulated gear history? Read against the sheet's
// OWN header across its full width, never the payload's: the sheet may be wider
// than the payload (a reverted userscript sends fewer columns), and the column
// we must protect could sit beyond nCols.
function gearHistoryPresent_(sh, lastRow) {
  if (lastRow < 2) return false;
  var width = sh.getLastColumn();
  if (width < 1) return false;
  var head = sh.getRange(1, 1, 1, width).getValues()[0];
  var col = -1;
  for (var i = 0; i < width; i++) {
    if (String(head[i]) === GEAR_COLUMN) { col = i + 1; break; }
  }
  if (col === -1) return false;
  var vals = sh.getRange(2, col, lastRow - 1, 1).getValues();
  for (var r = 0; r < vals.length; r++) {
    if (String(vals[r][0] === undefined ? '' : vals[r][0]) !== '') return true;
  }
  return false;
}

function isBlankRow_(arr) {
  for (var i = 0; i < arr.length; i++) {
    if (String(arr[i] === undefined ? '' : arr[i]) !== '') return false;
  }
  return true;
}

// Returns null when the headers agree, else the first disagreement.
//
// A payload column whose SHEET cell is BLANK is a new column, not drift: the
// userscript gained one and this tab has not seen it yet. Tolerating that is
// what lets a column be ADDED without mode:"replace" — and replace would
// destroy the accumulated gear union, so refusing here would push the operator
// straight into the one action that loses data.
//
// A SHIFT is still refused. Both cells non-empty and different means the column
// meanings have moved, which silently writes levels into XP cells; that is the
// failure the check was built for and it is untouched.
function headerMismatch_(sheetHeader, payloadHeader) {
  for (var i = 0; i < payloadHeader.length; i++) {
    var a = String(sheetHeader[i] === undefined ? '' : sheetHeader[i]);
    var b = String(payloadHeader[i]);
    if (a !== '' && a !== b) return { at: i, sheet: a, payload: b };
  }
  return null;
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
