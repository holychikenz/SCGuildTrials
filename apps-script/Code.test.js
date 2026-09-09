// =============================================================================
// Tests — apps-script/Code.gs  (the SIGN-UP + BUILDINGS write endpoint)
// -----------------------------------------------------------------------------
// Run:  node --test apps-script/Code.test.js
//
// Code.gs is plain ES5 with no imports, so it loads into a stubbed context and
// runs here. That matters because this script writes to the LIVE guild
// spreadsheet, and the only other way to exercise it is Deploy → new version →
// poke the real sheet.
//
// One endpoint now carries TWO mutually destructive block formats — a sign-up
// roster and a block of building/shrine levels — so what is pinned here is
// mostly the interlock that keeps them apart:
//
//   1) A buildings block reaches its own tab, and `Level` lands as a real
//      NUMBER. A stringified level would sort and chart as text on the sheet.
//   2) A buildings block sent to a SIGN-UP tab is refused. This is the one that
//      would quietly destroy data: the write is a clear-and-rewrite from A1, so
//      a 6-column levels block on "SC Trial Signup" would wipe the roster the
//      Python reader parses. The tab must be untouched, not partly written.
//   3) And the mirror: a sign-up roster sent to a Buildings tab is refused.
//      Same clobber, other direction — the module holds one endpoint URL and
//      two tab settings, so a mis-set tab name is an easy slip.
//   4) REGRESSION — sign-ups still behave exactly as before, ticks coerced to
//      native booleans. The format guard is new code on the live roster path.
//   5) The allowlist still refuses an unknown tab, and holds exactly the five
//      real tabs. There is deliberately no buildings test tab.
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

function load(sheetsByName) {
    const ctx = {
        SpreadsheetApp: { openById: () => ({ getSheetByName: (n) => sheetsByName[n] || null }) },
        ContentService: {
            MimeType: { JSON: "json" },
            createTextOutput: (s) => ({ _text: s, setMimeType() { return this; } }),
        },
        Array, String, Object, JSON, Math, Error, Number,
    };
    vm.createContext(ctx);
    vm.runInContext(CODE, ctx);
    ctx.SHARED_SECRET = SECRET;
    return ctx;
}

function post(ctx, body) {
    return JSON.parse(ctx.doPost({ postData: { contents: JSON.stringify(body) } })._text);
}

// --- fixtures ---------------------------------------------------------------

// A buildings block, exactly the shape the module's buildBuildingRows emits.
const B_HEADER = ["Building", "Hrid", "Kind", "Level", "Guild Id", "Captured At"];
const AT = "2026-09-07T12:00:00.000Z";
function buildingsRows(guildId = 4) {
    return [
        ["Guild Hall", "/guild_buildings/guild_hall", "building", 8, guildId, AT],
        ["Builder's Hall", "/guild_buildings/builders_hall", "building", 6, guildId, AT],
        ["Guild Garden", "/guild_buildings/garden", "building", 0, guildId, AT],   // unbuilt
        ["Shrine of Force", "/guild_shrines/force", "shrine", 5, guildId, AT],
        ["Shrine of Rarity", "/guild_shrines/rarity", "shrine", 0, guildId, AT],   // unbuilt
    ];
}

// A sign-up block, as guild-signup-sync's roster path emits it.
const S_HEADER = ["User", "Woodcutting", "Crafting", "Alchemy", "Milking", "Hedgehog", "Jellyfish"];
const S_ROWS = [
    ["Patbowl", "TRUE", "FALSE", "FALSE", "FALSE", "TRUE", "FALSE"],
    ["IronOwl", "FALSE", "FALSE", "TRUE", "FALSE", "FALSE", "TRUE"],
];

// --- 1. the buildings happy path --------------------------------------------

test("a buildings block is written to its own tab, with Level as a real number", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Buildings": sh });

    const res = post(ctx, { secret: SECRET, tab: "SC Buildings", header: B_HEADER, rows: buildingsRows(4) });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.tab, "SC Buildings");
    assert.strictEqual(res.format, "buildings", "the reply should name the format it wrote");
    assert.strictEqual(res.wroteRows, 5);
    assert.strictEqual(res.columns, 6);

    assert.strictEqual(sh._grid[0][0], "Building", "A1 must carry the format's own header");
    assert.strictEqual(sh._grid[1][0], "Guild Hall");
    assert.strictEqual(sh._grid[1][1], "/guild_buildings/guild_hall");

    // The point of cell_(): a level is a NUMBER, not "8". truthy_ would have
    // turned every one of these into a boolean.
    assert.strictEqual(sh._grid[1][3], 8);
    assert.strictEqual(typeof sh._grid[1][3], "number", "Level must be a numeric cell");
    assert.strictEqual(sh._grid[3][3], 0, "an unbuilt building is a literal 0");
    assert.strictEqual(typeof sh._grid[3][3], "number", "0 must not become false or ''");
    assert.strictEqual(sh._grid[1][4], 4, "Guild Id stays numeric");
    assert.strictEqual(sh._grid[1][5], AT, "the timestamp stays text");
});

test("the levels block goes to either guild's tab, independently", (t) => {
    const sc = makeSheet([], { maxCols: 26 });
    const li = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Buildings": sc, "LI Buildings": li });

    const res = post(ctx, { secret: SECRET, tab: "LI Buildings", header: B_HEADER, rows: buildingsRows(240) });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(li._grid[1][4], 240);
    assert.strictEqual(sc.getLastRow(), 0, "writing one guild's levels disturbed the other's tab");
});

// --- 2 & 3. the interlock, both directions ----------------------------------

test("a BUILDINGS block sent to a SIGN-UP tab is refused, and the roster survives", (t) => {
    // The destructive case. The write is a clear-and-rewrite from A1, so had
    // this gone through, the 40-member roster below would be five rows of levels.
    const signup = makeSheet([S_HEADER, ...S_ROWS], { maxCols: S_HEADER.length });
    const before = JSON.stringify(signup._grid);
    const ctx = load({ "SC Trial Signup": signup });

    const res = post(ctx, { secret: SECRET, tab: "SC Trial Signup", header: B_HEADER, rows: buildingsRows(4) });

    assert.strictEqual(res.ok, false);
    assert.match(res.error, /format mismatch/);
    assert.match(res.error, /buildings block/, "the error should name the block it refused");
    assert.match(res.error, /SC Trial Signup/, "and the tab it refused to write");
    assert.strictEqual(JSON.stringify(signup._grid), before,
        "the roster tab must be byte-identical — a partial write is still a loss");
});

test("a SIGN-UP block sent to a BUILDINGS tab is refused, and the levels survive", (t) => {
    const buildings = makeSheet([B_HEADER, ...buildingsRows(4)], { maxCols: B_HEADER.length });
    const before = JSON.stringify(buildings._grid);
    const ctx = load({ "SC Buildings": buildings });

    const res = post(ctx, { secret: SECRET, tab: "SC Buildings", header: S_HEADER, rows: S_ROWS });

    assert.strictEqual(res.ok, false);
    assert.match(res.error, /format mismatch/);
    assert.match(res.error, /signup block/);
    assert.strictEqual(JSON.stringify(buildings._grid), before, "the levels tab must be untouched");
});

test("a header naming neither format is refused before any tab is opened", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Buildings": sh });

    const res = post(ctx, {
        secret: SECRET, tab: "SC Buildings",
        header: ["Structure", "Hrid", "Level"], rows: [["Guild Hall", "/x", 1]],
    });

    assert.strictEqual(res.ok, false);
    assert.match(res.error, /col 0 must be "User" \(sign-ups\) or "Building" \(levels\)/);
    assert.strictEqual(sh.getLastRow(), 0);
});

// --- 4. REGRESSION: the sign-up path is unchanged ---------------------------

test("REGRESSION — a sign-up block still writes, ticks coerced to native booleans", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "chikenz-test": sh });

    const res = post(ctx, { secret: SECRET, tab: "chikenz-test", header: S_HEADER, rows: S_ROWS });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.format, "signup");
    assert.strictEqual(res.wroteRows, 2);
    assert.strictEqual(res.columns, 7);

    assert.strictEqual(sh._grid[0][0], "User");
    assert.strictEqual(sh._grid[1][0], "Patbowl");
    // Native booleans, not the strings that arrived — this is what
    // reader._to_bool reads back through the CSV export.
    assert.strictEqual(sh._grid[1][1], true);
    assert.strictEqual(typeof sh._grid[1][1], "boolean", "a tick must be a real boolean cell");
    assert.strictEqual(sh._grid[1][2], false);
    assert.strictEqual(sh._grid[2][3], true);
    assert.strictEqual(sh._grid[2][1], false);
});

test("REGRESSION — each guild's real sign-up tab still writes", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "LI Trial Signup": sh });
    const res = post(ctx, { secret: SECRET, tab: "LI Trial Signup", header: S_HEADER, rows: S_ROWS });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.format, "signup");
});

test("REGRESSION — a truncated header and a bad row width are still refused", (t) => {
    const ctx = load({ "chikenz-test": makeSheet() });

    const short = post(ctx, { secret: SECRET, tab: "chikenz-test", header: ["User", "Milking"], rows: [] });
    assert.strictEqual(short.ok, false);
    assert.match(short.error, /bad header: need at least 3 columns/);

    const narrow = post(ctx, {
        secret: SECRET, tab: "chikenz-test", header: S_HEADER, rows: [["Patbowl", "TRUE"]],
    });
    assert.strictEqual(narrow.ok, false);
    assert.match(narrow.error, /width 2 != header 7/);
});

// --- 5. the allowlist -------------------------------------------------------

test("an unknown tab is refused before the format is even considered", (t) => {
    const ctx = load({ Nope: makeSheet() });
    const res = post(ctx, { secret: SECRET, tab: "Nope", header: B_HEADER, rows: buildingsRows() });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /tab not allowed: Nope/);
});

test("doGet lists exactly the five real tabs, with their formats", (t) => {
    const ctx = load({});
    const res = JSON.parse(ctx.doGet()._text);

    assert.strictEqual(res.ok, true);
    assert.strictEqual(res.service, "guild-signup-sync");
    assert.strictEqual(res.allowedTabs.length, 5,
        "five tabs: three sign-up, two buildings — there is NO buildings test tab");
    assert.deepStrictEqual(res.allowedTabs.slice().sort(), [
        "LI Buildings", "LI Trial Signup", "SC Buildings", "SC Trial Signup", "chikenz-test",
    ]);
    assert.deepStrictEqual(res.tabFormats, {
        "chikenz-test": "signup",
        "SC Trial Signup": "signup",
        "LI Trial Signup": "signup",
        "SC Buildings": "buildings",
        "LI Buildings": "buildings",
    });
});

// --- guards (unchanged behaviour, re-pinned) --------------------------------

test("the wrong secret is refused", (t) => {
    const ctx = load({ "SC Buildings": makeSheet() });
    const res = post(ctx, { secret: "wrong", tab: "SC Buildings", header: B_HEADER, rows: [] });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /unauthorised/);
});

test("an unconfigured SHARED_SECRET refuses everything", (t) => {
    const ctx = load({ "SC Buildings": makeSheet() });
    ctx.SHARED_SECRET = "PASTE_A_LONG_RANDOM_SECRET_HERE";
    const res = post(ctx, { secret: "anything", tab: "SC Buildings", header: B_HEADER, rows: [] });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /set SHARED_SECRET/);
});

test("a missing Buildings tab is reported, never created", (t) => {
    // The manual-setup step is creating these two tabs by hand; getting the
    // message right is what tells the operator they skipped it.
    const ctx = load({ "SC Trial Signup": makeSheet() });
    const res = post(ctx, { secret: SECRET, tab: "SC Buildings", header: B_HEADER, rows: buildingsRows() });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /tab not found: "SC Buildings" — create it first/);
});

test("a null cell in a levels block lands blank, not as 0 or 'null'", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Buildings": sh });
    const res = post(ctx, {
        secret: SECRET, tab: "SC Buildings", header: B_HEADER,
        rows: [["Guild Hall", "/guild_buildings/guild_hall", "building", null, 4, null]],
    });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(sh._grid[1][3], "", "a null level must be blank, not a real 0");
    assert.strictEqual(sh._grid[1][5], "");
});
