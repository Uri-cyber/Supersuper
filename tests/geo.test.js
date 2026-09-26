"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const geo = require("../site/geo.js");

const GEO = {
  "_note": "לא קואורדינטה",
  "תל אביב - יפו": [32.0853, 34.7818],
  "ירושלים": [31.7683, 35.2137],
  "חיפה": [32.794, 34.9896],
  "ראשון לציון": [31.973, 34.7925]
};

test("haversine: תל אביב-ירושלים כ-54 ק\"מ", () => {
  const km = geo.haversineKm(GEO["תל אביב - יפו"], GEO["ירושלים"]);
  assert.ok(km > 51 && km < 57, "got " + km);
  assert.equal(geo.haversineKm(GEO["חיפה"], GEO["חיפה"]), 0);
  assert.equal(geo.haversineKm(null, GEO["חיפה"]), null);
});

test("cityCoord: התאמה מדויקת, ובלי רווחים ומקפים", () => {
  assert.deepEqual(geo.cityCoord("ירושלים", GEO), [31.7683, 35.2137]);
  assert.deepEqual(geo.cityCoord("תל אביב-יפו", GEO), [32.0853, 34.7818]);
  assert.deepEqual(geo.cityCoord("  תל אביב  -  יפו ", GEO), [32.0853, 34.7818]);
  assert.equal(geo.cityCoord("לא ידוע", GEO), null);
  assert.equal(geo.cityCoord("_note", GEO), null, "מפתח שאינו קואורדינטה אינו יישוב");
});

test("nearestCity: היישוב הקרוב לנקודה", () => {
  const n = geo.nearestCity([32.07, 34.79], GEO);
  assert.equal(n.city, "תל אביב - יפו");
  assert.ok(n.km < 3);
  assert.equal(geo.nearestCity([29.55, 34.95], GEO, 50), null, "אילת רחוקה מכל יישוב ברשימה");
});

const STORES = [
  { chain: "א", store_id: "1", city: "תל אביב - יפו", total: 120, items: 3, complete: true },
  { chain: "ב", store_id: "2", city: "ראשון לציון",   total: 100, items: 3, complete: true },
  { chain: "ג", store_id: "3", city: "ירושלים",       total: 90,  items: 3, complete: true },
  { chain: "ד", store_id: "4", city: "תל אביב - יפו", total: 60,  items: 2, complete: false },
  { chain: "ה", store_id: "5", city: "לא ידוע",       total: 50,  items: 3, complete: true },
  { chain: "ו", store_id: "6", city: "חיפה",          total: 80,  items: 3, complete: true }
];

test("rankNearby: רק בטווח, שלמים קודם, לפי סכום", () => {
  const r = geo.rankNearby(STORES, GEO["תל אביב - יפו"], 20, GEO);
  assert.deepEqual(r.list.map(s => s.chain), ["ב", "א"], "ראשון לציון זולה מתל אביב; ירושלים וחיפה מחוץ לטווח");
  assert.equal(r.complete, true);
  assert.equal(r.unknown, 1, "סניף בלי יישוב ידוע נספר ולא מוצג");
  assert.equal(r.farther, 2);
  assert.equal(r.in_radius, 3);
  assert.ok(r.list.every(s => typeof s.km === "number"));
});

test("rankNearby: בלי סניף שלם בטווח מוצגים חלקיים", () => {
  const partialOnly = STORES.filter(s => !s.complete || s.city !== "תל אביב - יפו" && s.city !== "ראשון לציון");
  const r = geo.rankNearby(partialOnly, GEO["תל אביב - יפו"], 20, GEO);
  assert.equal(r.complete, false);
  assert.deepEqual(r.list.map(s => s.chain), ["ד"]);
});

test("rankNearby: מגבלת תוצאות ורדיוס גדול", () => {
  const r = geo.rankNearby(STORES, GEO["תל אביב - יפו"], 500, GEO, 2);
  assert.equal(r.list.length, 2);
  assert.deepEqual(r.list.map(s => s.chain), ["ו", "ג"], "הזולים ביותר בארץ");
});
