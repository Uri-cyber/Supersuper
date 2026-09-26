/* חישובי מרחק ל"הזול בסביבה".

   לסניפים אין קואורדינטות בקבצים שהרשתות מפרסמות, יש רק שם יישוב וכתובת.
   לכן המרחק נמדד למרכז היישוב של הסניף (cities_geo.json), והוא מקורב:
   בעיר גדולה הסניף יכול להיות כמה קילומטרים מהמרכז. זה נאמר למשתמש במסך.

   הקובץ טעון גם בדפדפן (window.MehironGeo) וגם ב-Node לבדיקות. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.MehironGeo = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function toRad(d) { return d * Math.PI / 180; }

  /* מרחק בקילומטרים בין שתי נקודות [lat, lng] (נוסחת haversine) */
  function haversineKm(a, b) {
    if (!a || !b || a.length < 2 || b.length < 2) return null;
    var R = 6371;
    var dLat = toRad(b[0] - a[0]), dLng = toRad(b[1] - a[1]);
    var s = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(toRad(a[0])) * Math.cos(toRad(b[0])) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * R * Math.asin(Math.sqrt(s));
  }

  function norm(s) {
    return String(s || "").replace(/\s+/g, " ").replace(/\s*-\s*/g, " - ").trim();
  }
  function flat(s) { return norm(s).replace(/[\s\-]/g, ""); }

  /* הקואורדינטה של יישוב לפי שמו. התאמה מדויקת קודם, ואז בלי רווחים ומקפים,
     כי "תל אביב-יפו" ו"תל אביב - יפו" הם אותו מקום. */
  function cityCoord(name, geo) {
    if (!name || !geo) return null;
    var n = norm(name);
    if (Array.isArray(geo[n])) return geo[n];
    var f = flat(n);
    for (var k in geo) {
      if (Array.isArray(geo[k]) && flat(k) === f) return geo[k];
    }
    return null;
  }

  /* היישוב הקרוב ביותר לנקודה, לצורך תווית "ליד X" בלבד */
  function nearestCity(coords, geo, maxKm) {
    var best = null, bd = Infinity;
    for (var k in geo) {
      if (!Array.isArray(geo[k])) continue;
      var d = haversineKm(coords, geo[k]);
      if (d != null && d < bd) { bd = d; best = k; }
    }
    if (best == null || (maxKm && bd > maxKm)) return null;
    return { city: best, km: Math.round(bd * 10) / 10 };
  }

  /* דירוג סניפים בטווח.

     stores: רשומות עם city, total, items, complete (מתוך ניתוח הסל).
     סניפים שמוכרים את כל הסל מדורגים לפי סכום; רק אם אין כאלה בטווח
     מוצגים סניפים חלקיים, לפי מספר המוצרים ואז לפי סכום. סניף שהיישוב
     שלו אינו ידוע או אינו ברשימת הקואורדינטות נספר ולא מוצג. */
  function rankNearby(stores, origin, radiusKm, geo, limit) {
    limit = limit || 5;
    var inRadius = [], unknown = 0, farther = 0;
    (stores || []).forEach(function (s) {
      var c = cityCoord(s.city, geo);
      if (!c) { unknown++; return; }
      var km = haversineKm(origin, c);
      if (km == null || km > radiusKm) { farther++; return; }
      var copy = {};
      for (var k in s) copy[k] = s[k];
      copy.km = Math.round(km * 10) / 10;
      inRadius.push(copy);
    });
    var complete = inRadius.filter(function (s) { return s.complete; });
    var partial = inRadius.filter(function (s) { return !s.complete; });
    complete.sort(function (a, b) { return (a.total - b.total) || (a.km - b.km); });
    partial.sort(function (a, b) { return (b.items - a.items) || (a.total - b.total); });
    var list = complete.length ? complete : partial;
    return {
      list: list.slice(0, limit),
      complete: complete.length > 0,
      in_radius: inRadius.length,
      unknown: unknown,
      farther: farther
    };
  }

  return { haversineKm: haversineKm, cityCoord: cityCoord, nearestCity: nearestCity,
           rankNearby: rankNearby, norm: norm };
});
