// =============================================================================
// Tests — apps-script/profiles/Code.gs
// -----------------------------------------------------------------------------
// Run:  node --test apps-script/profiles/Code.test.js
//
// Code.gs is plain ES5 with no imports, so it loads into a stubbed context and
// runs here. That matters because this script writes to the LIVE guild
// spreadsheet, and the only other way to exercise it is Deploy → new version →
// poke the real sheet.
//
// What is pinned here, and why each one earned a test:
//
//   1) UPSERT PRESERVES MEMBERS ABSENT FROM THE PAYLOAD. The one that would
//      quietly destroy the roster. Profile cards are opened one at a time, so a
//      write may carry three members when the tab holds forty; a
//      clear-and-rewrite (correct for sign-ups, where one message carries the
//      whole roster) would delete the other thirty-seven.
//   2) The key is characterId, not the name, so a renamed member updates rather
//      than appearing twice. The game carries a `previousName` field, so renames
//      genuinely happen.
//   3) A sign-up payload sent here by mistake is refused. Pasting the wrong
//      /exec URL into the wrong module's settings is an easy slip, and the two
//      payloads are mutually destructive.
//   4) A fresh tab is 26 columns wide and a profile block is ~101, so the script
//      must widen the sheet or setValues throws live.
//   5) Nulls become blank cells, never 0 or "null" — a withheld tool or an
//      absent famePoints must not read as a real score of zero.
//   6) A header mismatch is refused rather than written through, because a
//      shifted column silently writes levels into XP cells.
// =============================================================================
"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CODE = fs.readFileSync(path.join(__dirname, "Code.gs"), "utf8");
const SECRET = "test-secret";

// --- fake Sheets ------------------------------------------------------------

function makeSheet(grid = [], { maxRows = 1000, maxCols = 26 } = {}) {
    const g = grid.map(r => r.slice());
    const ensure = (rows, cols) => {
        while (g.length < rows) g.push(new Array(cols).fill(""));
        for (const r of g) while (r.length < cols) r.push("");
    };

    return {
        _grid: g,
        getMaxRows: () => maxRows,
        getMaxColumns: () => maxCols,
        insertRowsAfter: (_after, n) => { maxRows += n; },
        insertColumnsAfter: (_after, n) => { maxCols += n; },
        getLastRow: () => {
            let last = 0;
            g.forEach((row, i) => { if (row.some(c => String(c ?? "") !== "")) last = i + 1; });
            return last;
        },
        getLastColumn: () => {
            let last = 0;
            for (const row of g) {
                row.forEach((c, j) => { if (String(c ?? "") !== "") last = Math.max(last, j + 1); });
            }
            return last;
        },
        getRange: (r, c, nr, nc) => {
            if (r + nr - 1 > maxRows || c + nc - 1 > maxCols) {
                throw new Error(`range out of bounds: rows ${r}..${r + nr - 1}/${maxRows}, ` +
                                `cols ${c}..${c + nc - 1}/${maxCols}`);
            }
            return {
                getValues: () => {
                    ensure(r + nr - 1, c + nc - 1);
                    const out = [];
                    for (let i = 0; i < nr; i++) out.push(g[r - 1 + i].slice(c - 1, c - 1 + nc));
                    return out;
                },
                setValues: (vals) => {
                    ensure(r + nr - 1, c + nc - 1);
                    for (let i = 0; i < nr; i++) {
                        for (let j = 0; j < nc; j++) g[r - 1 + i][c - 1 + j] = vals[i][j];
                    }
                },
                clearContent: () => {
                    ensure(r + nr - 1, c + nc - 1);
                    for (let i = 0; i < nr; i++) {
                        for (let j = 0; j < nc; j++) g[r - 1 + i][c - 1 + j] = "";
                    }
                },
            };
        },
    };
}

// `lock` lets a test simulate contention: { granted: false } makes tryLock fail
// the way a concurrent write from another machine would.
function load(sheetsByName, { lock = {} } = {}) {
    const { granted = true } = lock;
    const lockCalls = { tried: 0, released: 0 };
    const ctx = {
        SpreadsheetApp: { openById: () => ({ getSheetByName: (n) => sheetsByName[n] || null }) },
        // The gear column is MERGED rather than overwritten, which makes the
        // read-modify-write racy for the first time; Code.gs takes a script lock
        // around it. Without this stub the vm context throws ReferenceError.
        LockService: {
            getScriptLock: () => ({
                tryLock: () => { lockCalls.tried++; return granted; },
                releaseLock: () => { lockCalls.released++; },
            }),
        },
        ContentService: {
            MimeType: { JSON: "json" },
            createTextOutput: (s) => ({ _text: s, setMimeType() { return this; } }),
        },
        Array, String, Object, JSON, Math, Error,
    };
    vm.createContext(ctx);
    vm.runInContext(CODE, ctx);
    ctx.SHARED_SECRET = SECRET;
    ctx._lockCalls = lockCalls;
    return ctx;
}

function post(ctx, body) {
    return JSON.parse(ctx.doPost({ postData: { contents: JSON.stringify(body) } })._text);
}

// A header shaped like the real one: name first, characterId second.
function header(extra = []) {
    return ["name", "characterId", "guildId", "guildName", "totalLevel",
            "shrine_force_combat", "tool_milking", ...extra];
}
function row(name, id, { total = 2000, shrine = 4, tool = "Celestial Brush", extra = [] } = {}) {
    return [name, id, 4, "Survey Corps", total, shrine, tool, ...extra];
}

// --- the load-bearing one ---------------------------------------------------

test("UPSERT PRESERVES members absent from the payload", (t) => {
    const h = header();
    const sh = makeSheet([
        h,
        row("Patbowl", 60486, { total: 2128 }),
        row("IronOwl", 77257, { total: 2135 }),
        row("jodend", 8888, { total: 2059 }),
    ], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    // A later session opened only ONE card — jodend, now a level higher — plus a
    // member never seen before.
    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: h,
        rows: [row("jodend", 8888, { total: 2060 }), row("Smashcaster", 99999, { total: 2026, shrine: 0 })],
    });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.updated, 1, "jodend should have been updated in place");
    assert.strictEqual(res.appended, 1, "Smashcaster should have been appended");
    assert.strictEqual(res.totalRows, 4);

    const byName = {};
    for (let i = 1; i < sh._grid.length; i++) {
        if (String(sh._grid[i][0] || "") !== "") byName[sh._grid[i][0]] = sh._grid[i];
    }
    // THE POINT: neither was in the payload, and both survive.
    assert.ok(byName.Patbowl, "Patbowl was deleted — a replace would do this");
    assert.ok(byName.IronOwl, "IronOwl was deleted — a replace would do this");
    assert.strictEqual(byName.Patbowl[4], 2128, "an untouched member's data must not change");
    assert.strictEqual(byName.jodend[4], 2060, "the updated member should carry the new value");
});

test("upsert keys on characterId, so a rename updates rather than duplicates", (t) => {
    const h = header();
    const sh = makeSheet([h, row("OldName", 60486)], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, { secret: SECRET, tab: "SC Roster", header: h, rows: [row("NewName", 60486)] });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.updated, 1);
    assert.strictEqual(res.appended, 0, "a renamed member must not appear twice");
    assert.strictEqual(res.totalRows, 1);
    assert.strictEqual(sh._grid[1][0], "NewName");
});

test("mode replace rewrites the tab wholesale", (t) => {
    const h = header();
    const sh = makeSheet([h, row("Patbowl", 60486), row("IronOwl", 77257)], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", mode: "replace", header: h, rows: [row("jodend", 8888)],
    });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.replaced, true);
    assert.strictEqual(res.totalRows, 1, "replace is a deliberate wholesale overwrite");
    assert.strictEqual(sh._grid[1][0], "jodend");
    assert.strictEqual(String(sh._grid[2][0] || ""), "", "the old rows should be gone");
});

// --- the two endpoints cannot be confused -----------------------------------

test("a sign-up payload sent here is refused, with a hint", (t) => {
    const ctx = load({ "SC Roster": makeSheet() });
    // Exactly what guild-signup-sync sends, if its /exec URL were pasted wrong.
    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster",
        header: ["User", "Milking", "Crafting", "Alchemy", "Cooking"],
        rows: [["Patbowl", true, false, true, false]],
    });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /characterId/);
    assert.match(res.error, /sign-up payload/, "the error should name the likely cause");
});

test("sign-up tabs are not on this allowlist", (t) => {
    const ctx = load({ "SC Trial Signup": makeSheet() });
    const res = post(ctx, {
        secret: SECRET, tab: "SC Trial Signup", header: header(), rows: [row("Patbowl", 60486)],
    });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /tab not allowed/,
        "a 101-column block would bury the sheet the Python reader parses");
});

// --- geometry ---------------------------------------------------------------

test("a fresh 26-column tab is widened for a 101-column block", (t) => {
    const wide = [];
    for (let i = 0; i < 101; i++) wide.push("col" + i);
    wide[1] = "characterId";
    const r = new Array(101).fill(0);
    r[0] = "Patbowl"; r[1] = 60486;

    const sh = makeSheet([], { maxCols: 26 });        // Sheets' default width
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, { secret: SECRET, tab: "SC Roster", header: wide, rows: [r] });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.columns, 101);
    assert.ok(sh.getMaxColumns() >= 101, "the sheet was not widened; setValues would throw live");
});

test("appending past the sheet height grows it", (t) => {
    const h = header();
    const sh = makeSheet([h, row("A", 1)], { maxRows: 2, maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, { secret: SECRET, tab: "SC Roster", header: h, rows: [row("B", 2), row("C", 3)] });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.totalRows, 3);
    assert.ok(sh.getMaxRows() >= 4);
});

// --- values -----------------------------------------------------------------

test("nulls become empty cells, not zeros or the string 'null'", (t) => {
    const h = header(["famePoints"]);
    const sh = makeSheet([], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    // A hidden profile nulls its tools; famePoints is absent on most profiles.
    const r = row("Xannetine", 8616, { tool: null, extra: [null] });
    const res = post(ctx, { secret: SECRET, tab: "SC Roster", header: h, rows: [r] });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(sh._grid[1][6], "", "a withheld tool must be blank, not 'null'");
    assert.strictEqual(sh._grid[1][7], "", "an absent famePoints must be blank, not 0");
});

test("a real zero is written as a zero", (t) => {
    const h = header();
    const sh = makeSheet([], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    // An unbought shrine is a genuine 0 and must not be confused with a blank.
    const res = post(ctx, { secret: SECRET, tab: "SC Roster", header: h,
                            rows: [row("Smashcaster", 99999, { shrine: 0 })] });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(sh._grid[1][5], 0, "an unpurchased shrine must stay a literal 0");
});

// --- header drift -----------------------------------------------------------

test("a header mismatch is refused, naming the offending column", (t) => {
    const h = header();
    const sh = makeSheet([h, row("Patbowl", 60486)], { maxCols: h.length + 4 });
    const ctx = load({ "SC Roster": sh });

    // The operator turned on "include exact XP", inserting a column mid-block.
    const shifted = ["name", "characterId", "guildId", "guildName", "totalLevel",
                     "totalLevelXp", "shrine_force_combat", "tool_milking"];
    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: shifted,
        rows: [["Patbowl", 60486, 4, "Survey Corps", 2128, 1e9, 4, "Celestial Brush"]],
    });

    assert.strictEqual(res.ok, false);
    assert.match(res.error, /header mismatch at column 6/,
        "writing through a shifted header puts levels into XP cells");
    assert.match(res.error, /mode:"replace"/, "the error should say how to proceed");
});

// --- guards -----------------------------------------------------------------

test("a row with an empty characterId is refused", (t) => {
    const ctx = load({ "SC Roster": makeSheet() });
    const bad = row("Ghost", 60486);
    bad[1] = "";
    const res = post(ctx, { secret: SECRET, tab: "SC Roster", header: header(), rows: [bad] });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /empty characterId/);
});

test("a row whose width disagrees with the header is refused", (t) => {
    const ctx = load({ "SC Roster": makeSheet() });
    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: header(),
        rows: [["Patbowl", 60486, 4]],
    });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /width 3 != header 7/);
});

test("the wrong secret is refused", (t) => {
    const ctx = load({ "SC Roster": makeSheet() });
    const res = post(ctx, { secret: "wrong", tab: "SC Roster", header: header(), rows: [] });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /unauthorised/);
});

test("an unconfigured SHARED_SECRET refuses everything", (t) => {
    const ctx = load({ "SC Roster": makeSheet() });
    ctx.SHARED_SECRET = "PASTE_A_LONG_RANDOM_SECRET_HERE";
    const res = post(ctx, { secret: "anything", tab: "SC Roster", header: header(), rows: [] });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /set SHARED_SECRET/);
});

test("a missing tab is reported, never created", (t) => {
    const ctx = load({});
    const res = post(ctx, { secret: SECRET, tab: "SC Roster", header: header(), rows: [row("Patbowl", 60486)] });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /tab not found/);
});

test("an unknown mode is refused", (t) => {
    const ctx = load({ "SC Roster": makeSheet() });
    const res = post(ctx, { secret: SECRET, tab: "SC Roster", mode: "append",
                            header: header(), rows: [row("Patbowl", 60486)] });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /mode must be/);
});

test("doGet identifies this endpoint distinctly from the sign-up one", (t) => {
    const ctx = load({});
    const res = JSON.parse(ctx.doGet()._text);
    assert.strictEqual(res.ok, true);
    assert.strictEqual(res.service, "guild-profile-sheet",
        "the health check must be distinguishable from the sign-up endpoint's");
    assert.strictEqual(res.keyColumn, "characterId");
    // Both guilds' roster tabs must be writable.
    assert.ok(res.allowedTabs.includes("SC Roster"), "Survey Corps (id 4)");
    assert.ok(res.allowedTabs.includes("LI Roster"), "Lactose lntolerance (id 240)");
    // No sign-up tab may ever appear here.
    for (const t2 of ["SC Trial Signup", "LI Trial Signup", "chikenz-test"]) {
        assert.ok(!res.allowedTabs.includes(t2), `${t2} must not be writable by this endpoint`);
    }
});

test("each guild's roster tab is written independently", (t) => {
    const h = header();
    const sc = makeSheet([h, row("Patbowl", 60486)], { maxCols: h.length });
    const li = makeSheet([], { maxCols: h.length });
    const ctx = load({ "SC Roster": sc, "LI Roster": li });

    // A Lactose lntolerance member. Note the guild is identified by id 240, not
    // by name — "Lactose lntolerance" hides a lowercase 'l' where an 'I' appears.
    const res = post(ctx, {
        secret: SECRET, tab: "LI Roster", guildId: 240, guildName: "Lactose lntolerance",
        header: h, rows: [["Stranger", 12345, 240, "Lactose lntolerance", 1800, 0, "Holy Brush"]],
    });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.tab, "LI Roster");
    assert.strictEqual(res.guildId, 240, "the reply should echo the guild it wrote");
    assert.strictEqual(li._grid[1][0], "Stranger");
    // Survey Corps must be entirely untouched by a write to the other guild.
    assert.strictEqual(sc._grid[1][0], "Patbowl",
        "writing one guild's roster disturbed another's tab");
    assert.strictEqual(sc._grid.length, 2);
});

// =============================================================================
// The gear union — the one column that MERGES instead of overwriting
// -----------------------------------------------------------------------------
// Combat slots rotate with whatever a member is training, so a profile card
// shows a fraction of their gear. The userscript sends what THIS capture saw and
// we union it into the cell, keyed on hrid, keeping the higher enhancement
// level. What each test below earns its place for:
//
//   7)  The union itself: two captures of different gear must both survive.
//   8)  MAX on level, in both arrival orders. A +8 flail seen once must not be
//       demoted by a later capture that happens to show a fresh +3.
//   9)  A BLANK incoming cell must not wipe an accumulated one. This is what a
//       member hiding their gear sends, and what a REVERTED userscript sends —
//       and treating it as "they own nothing" would erase months of captures.
//   10) {"items":[]} likewise: a visible member wearing nothing tracked.
//   11) An unparseable EXISTING cell is left byte-identical. It may have been
//       hand-edited, or reveal a bug in our writer; either way it can hold data
//       no single machine could rebuild, so we never overwrite it blind.
//   12) An unparseable INCOMING cell never lands raw, or it would poison every
//       later merge on that member (see 11 — we would then refuse to touch it).
//   13) A runaway union is bounded rather than allowed to hit the ~50,000-char
//       cell limit mid-write.
//   14) ONLY this column merges. Every other cell is a snapshot and must still
//       be overwritten.
//   15) With no gearSeen column in the header, behaviour is exactly as before.
//   16) A header GROWING at the tail is accepted — the whole point, since the
//       remedy for a refusal is mode:"replace", which destroys the union.
//   17) replace over a populated gear column is refused. The single most
//       destructive action available, and a one-word setting in the module's UI.
//   18) Contention is answered, and the lock is always released.
// =============================================================================

const GEAR = "gearSeen";
const gearHeader = () => header([GEAR]);
const gj = (items) => JSON.stringify({ items: items });
const gearRow = (name, id, cell, opts = {}) =>
    row(name, id, Object.assign({}, opts, { extra: [cell] }));

// Reads the gear cell for a character out of the fake grid.
function gearOf(sh, id) {
    const head = sh._grid[0];
    const col = head.indexOf(GEAR);
    for (let i = 1; i < sh._grid.length; i++) {
        if (String(sh._grid[i][1]) === String(id)) return sh._grid[i][col];
    }
    return undefined;
}

test("the gear cell UNIONS by hrid across captures", (t) => {
    const h = gearHeader();
    const sh = makeSheet([
        h,
        gearRow("jodend", 8888, gj([{ hrid: "/items/chaotic_flail", level: 3 }])),
    ], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    // A later session caught the same member wearing a cape instead — the flail
    // is not equipped now, and must not be forgotten.
    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: h,
        rows: [gearRow("jodend", 8888, gj([{ hrid: "/items/sinister_cape", level: 0 }]))],
    });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.gearMerged, 1);
    assert.strictEqual(res.gearSkipped, 0);
    assert.deepStrictEqual(JSON.parse(gearOf(sh, 8888)).items, [
        { hrid: "/items/chaotic_flail", level: 3 },
        { hrid: "/items/sinister_cape", level: 0 },
    ], "both captures must survive, hrid-sorted");
});

test("the merge keeps the HIGHER enhancement level, whichever way round it arrives", (t) => {
    for (const [existing, incoming, expected] of [[8, 3, 8], [3, 8, 8]]) {
        const h = gearHeader();
        const sh = makeSheet([
            h,
            gearRow("jodend", 8888, gj([{ hrid: "/items/chaotic_flail", level: existing }])),
        ], { maxCols: h.length });
        const ctx = load({ "SC Roster": sh });

        const res = post(ctx, {
            secret: SECRET, tab: "SC Roster", header: h,
            rows: [gearRow("jodend", 8888, gj([{ hrid: "/items/chaotic_flail", level: incoming }]))],
        });

        assert.strictEqual(res.ok, true, res.error);
        assert.deepStrictEqual(JSON.parse(gearOf(sh, 8888)).items,
            [{ hrid: "/items/chaotic_flail", level: expected }],
            `+${existing} then +${incoming} should settle at +${expected}`);
    }
});

test("a BLANK incoming cell does not wipe an accumulated union", (t) => {
    // Two ways this arrives: the member set hideWearableItems, or the userscript
    // was reverted and no longer sends the column's content. Neither is a
    // statement that they own nothing.
    const h = gearHeader();
    const accumulated = gj([
        { hrid: "/items/chaotic_flail", level: 7 },
        { hrid: "/items/philosophers_ring", level: 2 },
    ]);
    const sh = makeSheet([h, gearRow("jodend", 8888, accumulated)], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: h,
        rows: [gearRow("jodend", 8888, "")],
    });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(gearOf(sh, 8888), accumulated, "a blank must contribute nothing, not erase");
});

test("an empty item list also contributes nothing and destroys nothing", (t) => {
    const h = gearHeader();
    const accumulated = gj([{ hrid: "/items/chaotic_flail", level: 7 }]);
    const sh = makeSheet([h, gearRow("jodend", 8888, accumulated)], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: h,
        rows: [gearRow("jodend", 8888, gj([]))],
    });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(gearOf(sh, 8888), accumulated);
});

test("an unparseable EXISTING cell is left byte-identical and reported", (t) => {
    const h = gearHeader();
    const handEdited = "chaotic flail +3, cape";     // somebody typed prose into it
    const sh = makeSheet([h, gearRow("jodend", 8888, handEdited)], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: h,
        rows: [gearRow("jodend", 8888, gj([{ hrid: "/items/sinister_cape", level: 0 }]))],
    });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.gearMerged, 0);
    assert.strictEqual(res.gearSkipped, 1, "the skip must be VISIBLE, not silent");
    assert.strictEqual(gearOf(sh, 8888), handEdited,
        "we never overwrite a cell we cannot read — it may hold months of captures");
    // The rest of the row still updates: one bad cell must not block the write.
    assert.strictEqual(res.updated, 1);
});

test("an unparseable INCOMING cell lands blank, never raw", (t) => {
    // Writing it through would poison every later merge on that member, because
    // an unparseable cell is then left untouched by design (see above).
    const h = gearHeader();
    const sh = makeSheet([h], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: h,
        rows: [
            gearRow("newcomer", 4242, '{"items":[{"hrid":"","level":3}]}'),   // empty hrid
            gearRow("another", 4243, '{"items":[{"hrid":"/items/x","level":-1}]}'), // negative
            gearRow("third", 4244, "{not json"),
        ],
    });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.gearSkipped, 3);
    for (const id of [4242, 4243, 4244]) {
        assert.strictEqual(gearOf(sh, id), "", `${id} should have a blank gear cell`);
    }
});

test("a runaway union is bounded rather than left to hit the cell limit", (t) => {
    const h = gearHeader();
    const kept = gj([{ hrid: "/items/chaotic_flail", level: 3 }]);
    const sh = makeSheet([h, gearRow("jodend", 8888, kept)], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    const many = [];
    for (let i = 0; i < 401; i++) many.push({ hrid: "/items/junk_" + i, level: 0 });

    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: h,
        rows: [gearRow("jodend", 8888, gj(many))],
    });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.gearSkipped, 1);
    assert.strictEqual(gearOf(sh, 8888), kept, "abandoning a merge preserves what was there");
});

test("ONLY the gear column merges — every other cell still overwrites", (t) => {
    const h = gearHeader();
    const sh = makeSheet([
        h,
        gearRow("jodend", 8888, gj([{ hrid: "/items/chaotic_flail", level: 3 }]),
                { total: 2128, shrine: 4 }),
    ], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    post(ctx, {
        secret: SECRET, tab: "SC Roster", header: h,
        rows: [gearRow("jodend", 8888, gj([{ hrid: "/items/sinister_cape", level: 0 }]),
                       { total: 2060, shrine: 6 })],
    });

    const head = sh._grid[0];
    assert.strictEqual(sh._grid[1][head.indexOf("totalLevel")], 2060,
        "a snapshot column must take the NEW value, not a merged one");
    assert.strictEqual(sh._grid[1][head.indexOf("shrine_force_combat")], 6);
    assert.strictEqual(JSON.parse(gearOf(sh, 8888)).items.length, 2);
});

test("with no gearSeen column, behaviour is exactly as it was before", (t) => {
    const h = header();
    const sh = makeSheet([h, row("Patbowl", 60486, { total: 2128 })], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: h,
        rows: [row("Patbowl", 60486, { total: 2200 })],
    });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.updated, 1);
    assert.strictEqual(res.gearMerged, 0);
    assert.strictEqual(res.gearSkipped, 0);
    assert.strictEqual(sh._grid[1][4], 2200);
});

test("a header GROWING at the tail is accepted, and the union starts clean", (t) => {
    // The reason this matters: the refusal's own advice is mode:"replace", which
    // would destroy the union. Adding a trailing column must therefore not be a
    // refusal at all.
    const before = header();                       // the tab as it stands today
    const after = gearHeader();                    // the module gained a column
    const sh = makeSheet([
        before,
        row("Patbowl", 60486, { total: 2128 }),
    ], { maxCols: before.length });
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: after,
        rows: [gearRow("Patbowl", 60486, gj([{ hrid: "/items/chaotic_flail", level: 3 }]),
                       { total: 2128 })],
    });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(sh._grid[0][after.length - 1], GEAR, "the new header cell is written");
    assert.deepStrictEqual(JSON.parse(gearOf(sh, 60486)).items,
        [{ hrid: "/items/chaotic_flail", level: 3 }],
        "an empty sheet cell merges cleanly — no special case needed");
});

test("replace over a populated gear column is REFUSED", (t) => {
    const h = gearHeader();
    const accumulated = gj([{ hrid: "/items/chaotic_flail", level: 7 }]);
    const sh = makeSheet([h, gearRow("jodend", 8888, accumulated)], { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", mode: "replace", header: h,
        rows: [gearRow("Smashcaster", 99999, gj([]))],
    });

    assert.strictEqual(res.ok, false);
    assert.match(res.error, /refusing replace/);
    assert.match(res.error, /discardGearHistory/, "the error must say how to proceed deliberately");
    assert.strictEqual(gearOf(sh, 8888), accumulated, "and nothing may have been touched");
});

test("replace proceeds with an explicit discard, or when there is no history to lose", (t) => {
    // Deliberate discard.
    const h = gearHeader();
    const sh = makeSheet([h, gearRow("jodend", 8888, gj([{ hrid: "/items/chaotic_flail", level: 7 }]))],
                         { maxCols: h.length });
    const ctx = load({ "SC Roster": sh });
    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", mode: "replace", discardGearHistory: true,
        header: h, rows: [gearRow("Smashcaster", 99999, gj([]))],
    });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.replaced, true);
    assert.strictEqual(res.totalRows, 1);

    // Nothing accumulated yet — a replace is harmless and must not be blocked.
    const h2 = gearHeader();
    const sh2 = makeSheet([h2, gearRow("jodend", 8888, "")], { maxCols: h2.length });
    const ctx2 = load({ "SC Roster": sh2 });
    const res2 = post(ctx2, {
        secret: SECRET, tab: "SC Roster", mode: "replace", header: h2,
        rows: [gearRow("Smashcaster", 99999, gj([]))],
    });
    assert.strictEqual(res2.ok, true, res2.error);
    assert.strictEqual(res2.replaced, true);
});

test("contention is answered cleanly, and the lock is always released", (t) => {
    const h = gearHeader();
    const accumulated = gj([{ hrid: "/items/chaotic_flail", level: 7 }]);

    // Another machine holds the lock. Without this guard both writes would read
    // the same cell and the second would discard the first's contribution.
    const sh = makeSheet([h, gearRow("jodend", 8888, accumulated)], { maxCols: h.length });
    const busy = load({ "SC Roster": sh }, { lock: { granted: false } });
    const res = post(busy, {
        secret: SECRET, tab: "SC Roster", header: h,
        rows: [gearRow("jodend", 8888, gj([{ hrid: "/items/sinister_cape", level: 0 }]))],
    });

    assert.strictEqual(res.ok, false);
    assert.match(res.error, /busy/);
    assert.strictEqual(gearOf(sh, 8888), accumulated, "a refused write must change nothing");
    assert.strictEqual(busy._lockCalls.released, 0, "nothing to release when nothing was taken");

    // And on the happy path it is released, so a later write is not locked out.
    const sh2 = makeSheet([h, gearRow("jodend", 8888, accumulated)], { maxCols: h.length });
    const ok = load({ "SC Roster": sh2 });
    post(ok, { secret: SECRET, tab: "SC Roster", header: h, rows: [gearRow("jodend", 8888, gj([]))] });
    assert.strictEqual(ok._lockCalls.tried, 1);
    assert.strictEqual(ok._lockCalls.released, 1);
});

test("the lock is released even when the write throws", (t) => {
    // A releaseLock() skipped on the error path would wedge the endpoint for
    // every later write, turning one transient fault into a dead deployment.
    const h = gearHeader();
    const sh = makeSheet([h], { maxCols: h.length });
    sh.getRange = () => { throw new Error("simulated Sheets failure"); };
    const ctx = load({ "SC Roster": sh });

    const res = post(ctx, {
        secret: SECRET, tab: "SC Roster", header: h,
        rows: [gearRow("jodend", 8888, gj([]))],
    });

    assert.strictEqual(res.ok, false);
    assert.match(res.error, /simulated Sheets failure/);
    assert.strictEqual(ctx._lockCalls.tried, 1);
    assert.strictEqual(ctx._lockCalls.released, 1, "the finally must run on the throw path");
});

test("the lock is released on an early RETURN inside it, not just on a throw", (t) => {
    // A missing tab returns from inside the locked section. `finally` covers a
    // return as well as a throw, but the two are different paths and a leak on
    // either would wedge every later write to the deployment — a mistyped tab
    // name should not take the endpoint down until the script times out.
    const ctx = load({ "SC Roster": makeSheet() });
    const res = post(ctx, {
        secret: SECRET, tab: "LI Roster",       // allowlisted, but not provided above
        header: gearHeader(), rows: [gearRow("jodend", 8888, gj([]))],
    });

    assert.strictEqual(res.ok, false);
    assert.match(res.error, /tab not found/);
    assert.strictEqual(ctx._lockCalls.tried, 1);
    assert.strictEqual(ctx._lockCalls.released, 1, "the finally must run on the return path");
});
