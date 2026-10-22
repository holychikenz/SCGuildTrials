// =============================================================================
// Tests — apps-script/Code.gs  (the SIGN-UP + BUILDINGS + COMBAT write endpoint)
// -----------------------------------------------------------------------------
// Run:  node --test apps-script/Code.test.js
//
// Code.gs is plain ES5 with no imports, so it loads into a stubbed context and
// runs here. That matters because this script writes to the LIVE guild
// spreadsheet, and the only other way to exercise it is Deploy → new version →
// poke the real sheet.
//
// One endpoint now carries THREE mutually destructive block formats — a
// sign-up roster, a block of building/shrine levels, and the optimiser's
// combat teams — so what is pinned here is mostly the interlock that keeps
// them apart:
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
//   5) The allowlist still refuses an unknown tab, and holds exactly the seven
//      real tabs. There is deliberately no buildings or combat test tab.
//   6) A combat block reaches its own tab with `Guild Id` numeric and the hrid
//      intact, and the interlock is THREE-way, not two: every one of the six
//      wrong-tab pairings is refused. The combat writer is a different program
//      from the other two (the optimiser, a Node CLI), holding this endpoint's
//      URL and its own tab names, so a mis-set name is the same easy slip —
//      and this block's tabs sit beside the hand-maintained ones.
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
    const formats = [];
    const ensure = (rows, cols) => {
        while (g.length < rows) g.push(new Array(cols).fill(""));
        for (const r of g) while (r.length < cols) r.push("");
    };

    return {
        _grid: g,
        _formats: formats,
        getMaxRows: () => maxRows,
        insertRowsAfter: (_after, n) => { maxRows += n; },
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
                setNumberFormat: (f) => { formats.push({ r, c, nr, nc, f }); },
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
// the way a concurrent write from another browser would (name_history only).
function load(sheetsByName, { lock = {} } = {}) {
    const { granted = true } = lock;
    const lockCalls = { tried: 0, released: 0, flushes: [], opened: [] };
    const ctx = {
        SpreadsheetApp: {
            openById: (id) => { lockCalls.opened.push(id); return { getSheetByName: (n) => sheetsByName[n] || null }; },
            // Records how many releases had happened when the flush ran, so a test
            // can pin that pending writes commit BEFORE the lock is let go.
            flush: () => { lockCalls.flushes.push({ releasedBefore: lockCalls.released }); },
        },
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
        Array, String, Object, JSON, Math, Error, Number,
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

// A combat-teams block, exactly the shape the optimiser's combatRowsFromAssignment
// emits (SCLIRoster optimizer/src/publish/combatTab.js). Two seats of one team and
// one of another, so the grouping the Python reader does has something to group.
const C_HEADER = ["Member", "Trial Hrid", "Team", "Role", "Slot", "Guild Id", "Generated At"];
function combatRows(guildId = 4, at = AT) {
    return [
        ["Yedic", "/guild_combat/chameleon", "SC Team 1", "tank", "tank 1", guildId, at],
        ["Pipsqueak", "/guild_combat/chameleon", "SC Team 1", "cursed", "cursed 1", guildId, at],
        ["IronOwl", "/guild_combat/hedgehog", "SC Team 2", "healer_blooming", "healer_blooming 1", guildId, at],
    ];
}

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
    // Three formats now, so the refusal names all three. A header that matches
    // none of them must be refused BEFORE the tab is opened — this is the guard
    // that stands between a typo'd header and a clear-and-rewrite from A1.
    assert.match(res.error,
        /col 0 must be "User" \(sign-ups\), "Building" \(levels\), "Member" \(combat teams\), "Upgrade" \(building value\) or "Character Id" \(name history\)/);
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

test("doGet lists exactly the eleven real tabs, with their formats", (t) => {
    const ctx = load({});
    const res = JSON.parse(ctx.doGet()._text);

    assert.strictEqual(res.ok, true);
    assert.strictEqual(res.service, "guild-signup-sync");
    assert.strictEqual(res.allowedTabs.length, 11,
        "eleven tabs: three sign-up, two buildings, two combat, two building value, " +
        "two name history — there is NO buildings or combat test tab");
    assert.deepStrictEqual(res.allowedTabs.slice().sort(), [
        "LI Building Value", "LI Buildings", "LI Combat Teams", "LI Name History",
        "LI Trial Signup", "SC Building Value", "SC Buildings", "SC Combat Teams",
        "SC Name History", "SC Trial Signup", "chikenz-test",
    ]);
    // doGet is the deployment's own health check: opening the /exec URL in a
    // browser is how the operator confirms a re-deploy actually took, so this
    // map is a shipped contract, not an internal detail.
    assert.deepStrictEqual(res.tabFormats, {
        "chikenz-test": "signup",
        "SC Trial Signup": "signup",
        "LI Trial Signup": "signup",
        "SC Buildings": "buildings",
        "LI Buildings": "buildings",
        "SC Combat Teams": "combat",
        "LI Combat Teams": "combat",
        "SC Building Value": "building_value",
        "LI Building Value": "building_value",
        "SC Name History": "name_history",
        "LI Name History": "name_history",
    });
});

// --- 6. the combat block, and the three-way interlock -----------------------

test("a combat block is written to its own tab, with Guild Id as a real number " +
     "and everything else text", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Combat Teams": sh });

    const res = post(ctx, { secret: SECRET, tab: "SC Combat Teams", header: C_HEADER, rows: combatRows(4) });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.tab, "SC Combat Teams");
    assert.strictEqual(res.format, "combat", "the reply should name the format it wrote");
    assert.strictEqual(res.wroteRows, 3);
    assert.strictEqual(res.columns, 7);

    assert.strictEqual(sh._grid[0][0], "Member", "A1 must carry the format's own header");
    assert.deepStrictEqual(sh._grid[0].slice(0, 7), C_HEADER, "the header goes down verbatim");
    assert.strictEqual(sh._grid[1][0], "Yedic");

    // The hrid is the contract between the three sides (the optimiser writes it,
    // combat.py guards its "/guild_combat/" prefix, the userscript derives the
    // tile slug from it), so it must survive as text, character for character.
    assert.strictEqual(sh._grid[1][1], "/guild_combat/chameleon");
    assert.strictEqual(typeof sh._grid[1][1], "string");
    assert.strictEqual(sh._grid[3][1], "/guild_combat/hedgehog");

    // Guild Id is the wrong-guild guard, and combat.py reads it as an int —
    // cell_() keeps it a NUMBER. truthy_ would have made it `true`.
    assert.strictEqual(sh._grid[1][5], 4);
    assert.strictEqual(typeof sh._grid[1][5], "number", "Guild Id must be a numeric cell");
    assert.strictEqual(sh._grid[1][6], AT, "the timestamp stays text");
    assert.strictEqual(sh._grid[2][4], "cursed 1", "the slot label stays text");
});

test("the combat block goes to either guild's tab, independently", (t) => {
    const sc = makeSheet([], { maxCols: 26 });
    const li = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Combat Teams": sc, "LI Combat Teams": li });

    const res = post(ctx, { secret: SECRET, tab: "LI Combat Teams", header: C_HEADER, rows: combatRows(240) });

    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(li._grid[1][5], 240);
    assert.strictEqual(sc.getLastRow(), 0, "publishing one guild's teams disturbed the other's tab");
});

test("a COMBAT block sent to a SIGN-UP tab is refused, and the roster survives", (t) => {
    // The destructive case for the new format. The optimiser is a separate
    // program holding this endpoint's URL and its own tab names; a mis-set name
    // would clear-and-rewrite the roster tab into three rows of team seats.
    const signup = makeSheet([S_HEADER, ...S_ROWS], { maxCols: S_HEADER.length });
    const before = JSON.stringify(signup._grid);
    const ctx = load({ "SC Trial Signup": signup });

    const res = post(ctx, { secret: SECRET, tab: "SC Trial Signup", header: C_HEADER, rows: combatRows(4) });

    assert.strictEqual(res.ok, false);
    assert.match(res.error, /format mismatch/);
    assert.match(res.error, /combat block/, "the error should name the block it refused");
    assert.match(res.error, /SC Trial Signup/, "and the tab it refused to write");
    assert.strictEqual(JSON.stringify(signup._grid), before,
        "the roster tab must be byte-identical — a partial write is still a loss");
});

test("a SIGN-UP block sent to a COMBAT tab is refused, and the teams survive", (t) => {
    const combat = makeSheet([C_HEADER, ...combatRows(4)], { maxCols: C_HEADER.length });
    const before = JSON.stringify(combat._grid);
    const ctx = load({ "SC Combat Teams": combat });

    const res = post(ctx, { secret: SECRET, tab: "SC Combat Teams", header: S_HEADER, rows: S_ROWS });

    assert.strictEqual(res.ok, false);
    assert.match(res.error, /format mismatch/);
    assert.match(res.error, /signup block/);
    assert.match(res.error, /SC Combat Teams/);
    assert.strictEqual(JSON.stringify(combat._grid), before, "the combat tab must be untouched");
});

test("a BUILDINGS block sent to a COMBAT tab is refused — the interlock is three-way", (t) => {
    // The pairing nothing else covers. With three formats there are six wrong
    // pairings, not two, and TAB_FORMAT is what makes them all one rule rather
    // than a growing list of special cases.
    const combat = makeSheet([C_HEADER, ...combatRows(4)], { maxCols: C_HEADER.length });
    const before = JSON.stringify(combat._grid);
    const ctx = load({ "SC Combat Teams": combat, "SC Buildings": makeSheet() });

    const res = post(ctx, { secret: SECRET, tab: "SC Combat Teams", header: B_HEADER, rows: buildingsRows(4) });

    assert.strictEqual(res.ok, false);
    assert.match(res.error, /format mismatch/);
    assert.match(res.error, /buildings block/);
    assert.match(res.error, /SC Combat Teams/);
    assert.strictEqual(JSON.stringify(combat._grid), before);

    // And the mirror, so the third pairing is pinned in both directions.
    const other = post(ctx, { secret: SECRET, tab: "SC Buildings", header: C_HEADER, rows: combatRows(4) });
    assert.strictEqual(other.ok, false);
    assert.match(other.error, /format mismatch/);
    assert.match(other.error, /combat block/);
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

// --- 7. the sign-up characterId column (rename safety) ----------------------

test("signup characterId column is written as a value, ticks stay booleans", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Trial Signup": sh });
    const header = [...S_HEADER, "characterId"];
    const res = post(ctx, {
        secret: SECRET, tab: "SC Trial Signup", header,
        rows: [
            ["Patbowl", "TRUE", "FALSE", "FALSE", "FALSE", "TRUE", "FALSE", "102437"],
            ["IronOwl", "FALSE", "FALSE", "TRUE", "FALSE", "FALSE", "TRUE", 55],
            ["NoId", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", ""],
        ],
    });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.columns, 8);
    assert.strictEqual(sh._grid[0][7], "characterId");
    assert.strictEqual(sh._grid[1][7], "102437", "a string id is kept, not coerced to a boolean");
    assert.strictEqual(sh._grid[2][7], 55, "a numeric id stays a number");
    assert.strictEqual(sh._grid[3][7], "", "an empty id cell stays blank, not false");
    assert.strictEqual(sh._grid[1][1], true, "ticks are still booleans");
    assert.strictEqual(sh._grid[1][6], false);
});

test("a header cell that merely resembles characterId is still a tick", (t) => {
    // The header match is EXACT per the contract, so a differently-cased cell is
    // treated as an ordinary trial column and coerced by truthy_.
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Trial Signup": sh });
    const res = post(ctx, {
        secret: SECRET, tab: "SC Trial Signup", header: [...S_HEADER, "CharacterID"],
        rows: [["Patbowl", "TRUE", "FALSE", "FALSE", "FALSE", "TRUE", "FALSE", "102437"]],
    });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(sh._grid[1][7], false);
});

// --- 8. the Name History block: an UPSERT, not a rewrite (rename safety) ----

const H_HEADER = ["Character Id", "Name", "Guild Id", "First Seen", "Last Seen"];
const T1 = "2026-09-01T00:00:00.000Z";
const T2 = "2026-09-10T00:00:00.000Z";
const T0 = "2026-08-01T00:00:00.000Z";
const T3 = "2026-10-01T00:00:00.000Z";

test("a name history block on an EMPTY tab writes the header and every row as text", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Name History": sh });
    const res = post(ctx, {
        secret: SECRET, tab: "SC Name History", header: H_HEADER,
        rows: [[102437, "NewName", 4, T3, T3], ["555", "Other", "4", T1, T2]],
    });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.format, "name_history");
    assert.strictEqual(res.tab, "SC Name History");
    assert.strictEqual(res.inserted, 2);
    assert.strictEqual(res.updated, 0);
    assert.deepStrictEqual(sh._grid[0].slice(0, 5), H_HEADER);
    assert.deepStrictEqual(sh._grid[1].slice(0, 5), ["102437", "NewName", "4", T3, T3]);
    for (const row of sh._grid.slice(0, 3)) {
        for (const c of row.slice(0, 5)) assert.strictEqual(typeof c, "string");
    }
    assert.ok(sh._formats.some(f => f.f === "@" && f.r === 1 && f.c === 1 && f.nr === 3 && f.nc === 5),
        "the written range must be formatted as text before the values land");
    assert.strictEqual(ctx._lockCalls.released, 1);
});

test("name history flushes its writes BEFORE releasing the lock", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Name History": sh });
    const res = post(ctx, {
        secret: SECRET, tab: "SC Name History", header: H_HEADER,
        rows: [[102437, "NewName", 4, T3, T3]],
    });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(ctx._lockCalls.flushes.length, 1, "pending writes must be flushed");
    assert.strictEqual(ctx._lockCalls.flushes[0].releasedBefore, 0,
        "the flush must run while the lock is still held");
    assert.strictEqual(ctx._lockCalls.released, 1);
});

test("upsert: an existing (id, name) widens First/Last Seen, takes a new Guild Id, and appends new pairs", (t) => {
    const other = ["555", "Other", "4", T1, T2];
    const sh = makeSheet([H_HEADER, ["102437", "OldName", "4", T1, T2], other.slice()], { maxCols: 26 });
    const ctx = load({ "SC Name History": sh });
    const res = post(ctx, {
        secret: SECRET, tab: "SC Name History", header: H_HEADER,
        rows: [["102437", "OldName", "240", T0, T3], ["102437", "NewName", "4", T3, T3]],
    });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.updated, 1);
    assert.strictEqual(res.inserted, 1);
    assert.deepStrictEqual(sh._grid[1].slice(0, 5), ["102437", "OldName", "240", T0, T3]);
    assert.deepStrictEqual(sh._grid[2].slice(0, 5), other, "an untouched row stays byte-equal");
    assert.deepStrictEqual(sh._grid[3].slice(0, 5), ["102437", "NewName", "4", T3, T3]);
});

test('upsert: "" never overwrites a timestamp or a Guild Id', (t) => {
    const sh = makeSheet([H_HEADER, ["102437", "OldName", "4", T1, T2]], { maxCols: 26 });
    const ctx = load({ "SC Name History": sh });
    const res = post(ctx, {
        secret: SECRET, tab: "SC Name History", header: H_HEADER,
        rows: [["102437", "OldName", "", "", ""]],
    });
    assert.strictEqual(res.ok, true, res.error);
    assert.deepStrictEqual(sh._grid[1].slice(0, 5), ["102437", "OldName", "4", T1, T2]);
});

test("rows with an empty id, an empty name or a non-numeric id are skipped and counted", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Name History": sh });
    const res = post(ctx, {
        secret: SECRET, tab: "SC Name History", header: H_HEADER,
        rows: [["", "A", "4", T1, T1], ["7", "", "4", T1, T1], ["Yedic", "Yedic", "4", T1, T1],
               ["8", "Good", "4", T1, T1]],
    });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(res.rejected, 3);
    assert.strictEqual(res.inserted, 1);
    assert.strictEqual(sh.getLastRow(), 2);
    assert.deepStrictEqual(sh._grid[1].slice(0, 2), ["8", "Good"]);
});

test("a header mismatch on the existing tab is refused and the tab is untouched", (t) => {
    const sh = makeSheet([["Character Id", "Name", "Guild", "First Seen", "Last Seen"], ["1", "A", "4", T1, T1]],
                         { maxCols: 26 });
    const before = JSON.stringify(sh._grid);
    const ctx = load({ "SC Name History": sh });
    const res = post(ctx, { secret: SECRET, tab: "SC Name History", header: H_HEADER, rows: [["2", "B", "4", T1, T1]] });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /header mismatch at column 3/);
    assert.strictEqual(JSON.stringify(sh._grid), before);
    assert.strictEqual(ctx._lockCalls.released, 1, "the lock is released on refusal too");
});

test("a payload header that is not exactly the five columns is refused", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Name History": sh });
    const wide = post(ctx, { secret: SECRET, tab: "SC Name History", header: [...H_HEADER, "Extra"],
                             rows: [["1", "A", "4", T1, T1, "x"]] });
    assert.strictEqual(wide.ok, false);
    assert.match(wide.error, /name history block is exactly/);
    const swapped = post(ctx, { secret: SECRET, tab: "SC Name History",
                                header: ["Character Id", "Guild Id", "Name", "First Seen", "Last Seen"],
                                rows: [["1", "4", "A", T1, T1]] });
    assert.strictEqual(swapped.ok, false);
    assert.strictEqual(sh.getLastRow(), 0);
});

test("the name history interlock: no other block reaches it, and it reaches no other tab", (t) => {
    const signup = makeSheet([S_HEADER, ...S_ROWS], { maxCols: S_HEADER.length });
    const hist = makeSheet([H_HEADER, ["1", "A", "4", T1, T1]], { maxCols: 26 });
    const combatTab = makeSheet([], { maxCols: 26 });
    const sBefore = JSON.stringify(signup._grid);
    const hBefore = JSON.stringify(hist._grid);
    const ctx = load({ "SC Trial Signup": signup, "SC Name History": hist, "LI Name History": hist,
                       "LI Combat Teams": combatTab });

    const a = post(ctx, { secret: SECRET, tab: "SC Trial Signup", header: H_HEADER, rows: [["2", "B", "4", T1, T1]] });
    assert.strictEqual(a.ok, false);
    assert.match(a.error, /format mismatch/);
    assert.strictEqual(JSON.stringify(signup._grid), sBefore);

    const b = post(ctx, { secret: SECRET, tab: "SC Name History", header: S_HEADER, rows: S_ROWS });
    assert.strictEqual(b.ok, false);
    assert.match(b.error, /format mismatch/);
    const c = post(ctx, { secret: SECRET, tab: "LI Name History", header: C_HEADER, rows: combatRows(240) });
    assert.strictEqual(c.ok, false);
    assert.match(c.error, /format mismatch/);
    assert.strictEqual(JSON.stringify(hist._grid), hBefore);

    const d = post(ctx, { secret: SECRET, tab: "LI Combat Teams", header: H_HEADER, rows: [["2", "B", "4", T1, T1]] });
    assert.strictEqual(d.ok, false);
    assert.strictEqual(combatTab.getLastRow(), 0);
});

test("a busy lock refuses without writing", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Name History": sh }, { lock: { granted: false } });
    const res = post(ctx, { secret: SECRET, tab: "SC Name History", header: H_HEADER, rows: [["1", "A", "4", T1, T1]] });
    assert.strictEqual(res.ok, false);
    assert.match(res.error, /busy/);
    assert.strictEqual(sh.getLastRow(), 0);
});

test("the name history grows the sheet when it runs out of rows", (t) => {
    const sh = makeSheet([H_HEADER], { maxRows: 2, maxCols: 26 });
    const ctx = load({ "SC Name History": sh });
    const res = post(ctx, { secret: SECRET, tab: "SC Name History", header: H_HEADER,
                            rows: [["1", "A", "4", T1, T1], ["2", "B", "4", T1, T1], ["3", "C", "4", T1, T1]] });
    assert.strictEqual(res.ok, true, res.error);
    assert.strictEqual(sh.getLastRow(), 4);
});

// --- audit 2026-10: the spreadsheet id is pinned; every rewrite takes the lock ---

test("a caller-supplied spreadsheetId is ignored: SPREADSHEET_ID is always opened", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    const ctx = load({ "SC Buildings": sh });
    const res = post(ctx, { secret: SECRET, tab: "SC Buildings", header: B_HEADER,
                            rows: buildingsRows(4), spreadsheetId: "attacker-sheet" });
    assert.strictEqual(res.ok, true, res.error);
    assert.deepStrictEqual(ctx._lockCalls.opened, [ctx.SPREADSHEET_ID]);
});

for (const [tab, header, rows] of [
    ["SC Trial Signup", S_HEADER, S_ROWS],
    ["SC Buildings", B_HEADER, buildingsRows(4)],
    ["SC Combat Teams", C_HEADER, combatRows(4)],
]) {
    test(`a ${tab} rewrite under a busy lock refuses and leaves the tab untouched`, (t) => {
        const before = [["old", "a", "b"], ["x", "y", "z"]];
        const sh = makeSheet(before, { maxCols: 26 });
        const ctx = load({ [tab]: sh }, { lock: { granted: false } });
        const res = post(ctx, { secret: SECRET, tab, header, rows });
        assert.strictEqual(res.ok, false);
        assert.match(res.error, /busy/);
        assert.deepStrictEqual(sh._grid.map(r => r.slice(0, 3)), before);
    });

    test(`a ${tab} rewrite flushes, then releases the lock`, (t) => {
        const sh = makeSheet([], { maxCols: 26 });
        const ctx = load({ [tab]: sh });
        const res = post(ctx, { secret: SECRET, tab, header, rows });
        assert.strictEqual(res.ok, true, res.error);
        assert.strictEqual(ctx._lockCalls.tried, 1);
        assert.strictEqual(ctx._lockCalls.released, 1);
        assert.deepStrictEqual(ctx._lockCalls.flushes, [{ releasedBefore: 0 }]);
    });
}

test("a rewrite that throws mid-write still releases the lock", (t) => {
    const sh = makeSheet([], { maxCols: 26 });
    sh.getMaxColumns = () => { throw new Error("sheet gone"); };
    const ctx = load({ "SC Buildings": sh });
    const res = post(ctx, { secret: SECRET, tab: "SC Buildings", header: B_HEADER, rows: buildingsRows(4) });
    assert.strictEqual(res.ok, false);
    assert.strictEqual(ctx._lockCalls.released, 1);
});
