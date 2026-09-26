"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const alerts = require("../site/alerts.js");

const LATEST = "2026-09-25";
const WATCH = [
  { barcode: "1", name: "חלב" },
  { barcode: "2", name: "לחם" },
  { barcode: "3", name: "קפה" },
  { barcode: "4", name: "חדש" },
  { barcode: "5", name: "יציב" }
];
const SERIES = {
  "1": [{ date: "2026-09-20", median: 6.9, n_stores: 900 }, { date: "2026-09-25", median: 7.9, n_stores: 910 }],
  "2": [{ date: "2026-09-01", median: 8.0, n_stores: 500 }, { date: "2026-09-25", median: 6.0, n_stores: 480 }],
  "3": [{ date: "2026-09-10", median: 30.0, n_stores: 700 }, { date: "2026-09-18", median: 29.0, n_stores: 690 }],
  "4": [{ date: "2026-09-25", median: 4.5, n_stores: 300 }],
  "5": [{ date: "2026-09-24", median: 5.0, n_stores: 400 }, { date: "2026-09-25", median: 5.0, n_stores: 401 }]
};

test("pct: עיגול לעשירית, ואפס מגן מחלוקה", () => {
  assert.equal(alerts.pct(7.9, 6.9), 14.5);
  assert.equal(alerts.pct(6, 8), -25);
  assert.equal(alerts.pct(5, 0), null);
});

test("diffWatch: שינוי בעדכון האחרון מול ללא שינוי", () => {
  const d = alerts.diffWatch(WATCH, SERIES, LATEST);
  assert.deepEqual(d.changed.map(c => c.barcode), ["2", "1"], "ממוין לפי גודל השינוי המוחלט");
  const milk = d.changed[1];
  assert.equal(milk.old, 6.9);
  assert.equal(milk.now, 7.9);
  assert.equal(milk.pct, 14.5);
  assert.equal(milk.prev_date, "2026-09-20");
  assert.equal(milk.date, LATEST);
  assert.equal(milk.stores, 910);
  const bread = d.changed[0];
  assert.equal(bread.pct, -25);
});

test("diffWatch: ללא שינוי, נתון ראשון, וחסר", () => {
  const d = alerts.diffWatch(WATCH, SERIES, LATEST);
  const byCode = {};
  d.unchanged.forEach(u => { byCode[u.barcode] = u; });
  assert.equal(byCode["3"].price, 29.0);
  assert.equal(byCode["3"].since, "2026-09-18", "השינוי האחרון היה לפני העדכון האחרון");
  assert.equal(byCode["4"].first, true, "מוצר עם שורה ראשונה היום אינו 'שינוי'");
  assert.equal(byCode["5"].price, 5.0, "שורה חדשה עם אותו חציון אינה שינוי מחיר");
  assert.equal(d.missing.length, 0);
  const d2 = alerts.diffWatch([{ barcode: "9", name: "אין" }], SERIES, LATEST);
  assert.equal(d2.missing.length, 1);
  assert.equal(d2.missing[0].name, "אין");
});

test("diffWatch: רשימה ריקה", () => {
  const d = alerts.diffWatch([], {}, LATEST);
  assert.deepEqual(d, { changed: [], unchanged: [], missing: [], latest: LATEST });
});

test("toggleWatch/isWatched: הוספה והסרה בלי לשנות את המקור", () => {
  const a = [];
  const b = alerts.toggleWatch(a, { barcode: "7", name: "גבינה", tint: "#eee" });
  assert.equal(a.length, 0);
  assert.equal(b.length, 1);
  assert.equal(alerts.isWatched(b, "7"), true);
  const c = alerts.toggleWatch(b, { barcode: "7" });
  assert.equal(c.length, 0);
  assert.equal(alerts.isWatched(c, "7"), false);
  assert.equal(alerts.isWatched(null, "7"), false);
});
