/* התראות מחיר: מוצרים במעקב, ומה השתנה בהם בעדכון היומי האחרון.

   "השתנה בעדכון האחרון" = לסדרה הארצית של המוצר (market_daily, שורה רק
   ביום שבו משהו השתנה) יש שורה בתאריך הנתונים האחרון. המחיר הישן הוא
   החציון בשורה שלפניה. מוצר בלי שורה כזו לא השתנה מאז התאריך של השורה
   האחרונה שלו, וזה מה שמוצג.

   רשימת המעקב עצמה נשמרת ב-localStorage של המשתמש בלבד.
   הקובץ טעון גם בדפדפן (window.MehironAlerts) וגם ב-Node לבדיקות. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.MehironAlerts = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function pct(now, before) {
    if (!before) return null;
    return Math.round((now - before) / before * 1000) / 10;
  }

  /* watch: [{barcode, name}], series: {barcode: [{date, median, n_stores}...] עולה לפי תאריך} */
  function diffWatch(watch, series, latestDate) {
    var changed = [], unchanged = [], missing = [];
    (watch || []).forEach(function (w) {
      var v = (series && series[w.barcode]) || [];
      if (!v.length) {
        missing.push({ barcode: w.barcode, name: w.name, reason: "אין למוצר היסטוריית מחיר ארצית" });
        return;
      }
      var last = v[v.length - 1], prev = v[v.length - 2];
      if (last.date === latestDate && prev && last.median !== prev.median) {
        changed.push({
          barcode: w.barcode, name: w.name,
          old: prev.median, now: last.median, pct: pct(last.median, prev.median),
          date: last.date, prev_date: prev.date, stores: last.n_stores
        });
      } else {
        unchanged.push({
          barcode: w.barcode, name: w.name, price: last.median,
          since: last.date, stores: last.n_stores,
          first: !prev && last.date === latestDate
        });
      }
    });
    changed.sort(function (a, b) { return Math.abs(b.pct) - Math.abs(a.pct); });
    return { changed: changed, unchanged: unchanged, missing: missing, latest: latestDate };
  }

  function isWatched(list, barcode) {
    return (list || []).some(function (w) { return w.barcode === barcode; });
  }

  /* מחזיר רשימה חדשה: מוסיף אם חסר, מסיר אם קיים */
  function toggleWatch(list, item) {
    list = list || [];
    if (isWatched(list, item.barcode)) {
      return list.filter(function (w) { return w.barcode !== item.barcode; });
    }
    return list.concat([{ barcode: item.barcode, name: item.name || "", tint: item.tint || "" }]);
  }

  return { diffWatch: diffWatch, isWatched: isWatched, toggleWatch: toggleWatch, pct: pct };
});
