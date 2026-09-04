/* מחירון - שכבת נתונים.
   שני מימושים שמחזירים בדיוק את אותם מבנים:
     server  - קורא ל-/api/* של שרת הפייתון המקומי
     sqlite  - קורא את קובץ ה-SQLite ישירות מהענן, בחתיכות, דרך בקשות HTTP Range
   כך שכל קוד התצוגה ב-app.js לא יודע ולא אכפת לו מאיפה הנתונים מגיעים. */
(function () {
"use strict";

var UNKNOWN = "לא ידוע";
var NOTE_NO_STORE_FILE = "הרשת לא מפרסמת קובץ סניפים";
var FRESH_DAYS = 7;
var TINTS = ["#bfe9ff", "#ffd9e8", "#ffe9a8", "#d6f5c9", "#e3dcff", "#ffd6c2", "#c9f2ee", "#fff0c2"];
var HEAT = ["#1fb85a", "#7fd63a", "#ffcb3d", "#ff9a3d", "#ff6a4d", "#ff4d4d"];

function money(v) { return Math.round(Number(v) * 100) / 100; }
function pct(a, b) { return b ? Math.round((a - b) / b * 1000) / 10 : 0; }
function tintFor(barcode) {
  var d = String(barcode).replace(/\D/g, "") || "0";
  return TINTS[parseInt(d.slice(-2) || "0", 10) % TINTS.length];
}
function heatColor(i, n) {
  if (n <= 1) return HEAT[0];
  return HEAT[Math.round(i / (n - 1) * (HEAT.length - 1))];
}
function median(sorted) {
  var n = sorted.length;
  if (!n) return 0;
  var m = n >> 1;
  return n % 2 ? sorted[m] : (sorted[m - 1] + sorted[m]) / 2;
}
function addDays(iso, days) {
  var d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

// ------------------------------------------------------------------ server mode
function ServerApi() {
  function get(path) {
    return fetch(path).then(function (r) {
      if (!r.ok) throw new Error("שגיאת שרת " + r.status);
      return r.json();
    });
  }
  function post(path, body) {
    return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
                         body: JSON.stringify(body) }).then(function (r) {
      if (!r.ok) throw new Error("שגיאת שרת " + r.status);
      return r.json();
    });
  }
  return {
    mode: "server",
    init: function () { return Promise.resolve(); },
    meta: function () { return get("/api/meta"); },
    home: function () { return get("/api/home"); },
    search: function (q, limit) {
      return get("/api/search?limit=" + (limit || 30) + "&q=" + encodeURIComponent(q));
    },
    product: function (o) {
      return get("/api/product?barcode=" + encodeURIComponent(o.barcode) +
        (o.city ? "&city=" + encodeURIComponent(o.city) : "") +
        (o.chains ? "&chains=" + encodeURIComponent(o.chains.join("|")) : "") +
        (o.includeOld ? "&include_old=1" : ""));
    },
    market: function (barcode) {
      return get("/api/market" + (barcode ? "?barcode=" + encodeURIComponent(barcode) : ""));
    },
    basket: function (items, city, includeOld) {
      return post("/api/basket", { items: items, city: city, include_old: includeOld });
    },
    receipt: function (text, city) { return post("/api/receipt", { text: text, city: city }); }
  };
}

// ------------------------------------------------------------------ sqlite mode
// כל שאילתה היא בקשת רשת, ולכן הכל כאן אסינכרוני. במקומות שבהם הקוד המקורי
// הריץ שאילתה בתוך לולאה, מאוחדת כאן שאילתה אחת והחישוב נעשה בזיכרון.
function SqliteApi(cfg) {
  var worker = null;
  // ה-Worker מפענח כתובות יחסיות מול המיקום של עצמו, לא של הדף.
  function abs(u) { return new URL(u, document.baseURI).href; }
  var cbs = {};            // קוד יישוב של הלמ"ס -> שם
  var alias = {};          // איות מנורמל -> שם רשמי
  var metaCache = null;
  var cityRawCache = null;
  var latestDate = null;
  var pre = {};            // ערכים שחושבו מראש בזמן בניית המסד
  var storeIdx = null;     // מפתח "רשת מספר" -> פרטי הסניף, בזיכרון

  // טבלת הסניפים קטנה (כ-2,000 שורות) ונטענת פעם אחת. בלעדיה כל עמוד מוצר
  // היה מבצע אלפי גישות אקראיות למסד רק כדי לצרף שם עיר לכל מחיר.
  function buildStoreIdx() {
    storeIdx = {};
    (pre.stores || []).forEach(function (r) {
      storeIdx[r.chain + " " + r.store_id] = r;
    });
  }
  function lookupStore(chain, storeId) {
    return storeIdx ? storeIdx[chain + " " + storeId] || null : null;
  }

  function q(sql, args) { return worker.db.query(sql, args || []); }

  function canonKey(name) {
    return String(name || "").trim()
      .replace(/[־–]/g, "-").replace(/\s*-\s*/g, " - ")
      .replace(/\s+/g, " ").replace(/קרית /g, "קריית ");
  }
  // מיפוי איות בלבד (קרית/קריית, מקפים) לשם הרשמי. לא ניחוש של עיר חסרה.
  function buildAlias() {
    Object.keys(cbs).forEach(function (code) {
      var full = cbs[code];
      var k = canonKey(full);
      if (!(k in alias)) alias[k] = full;
      var short = full.split(" - ")[0].trim();
      if (short !== full && !(canonKey(short) in alias)) alias[canonKey(short)] = full;
    });
  }
  function cityDisplay(raw) {
    raw = String(raw == null ? "" : raw).trim();
    if (!raw || raw === UNKNOWN) return [UNKNOWN, "העיר חסרה בקובץ הרשת"];
    if (/^\d+$/.test(raw)) {
      var name = cbs[String(parseInt(raw, 10))];
      if (name) return [name, ""];
      return [UNKNOWN, "הרשת פרסמה קוד יישוב שאינו מוכר (" + raw + ")"];
    }
    return [alias[canonKey(raw)] || raw, ""];
  }
  function cityGroup(raw) { return cityDisplay(raw)[0]; }
  function freshCutoff() { return addDays(latestDate, -FRESH_DAYS); }
  function placeholders(n) { return new Array(n).fill("?").join(","); }

  async function cityRawValues(city) {
    if (!city) return null;
    if (!cityRawCache) {
      cityRawCache = {};
      var seen = {};
      var raws = storeIdx
        ? Object.keys(storeIdx).map(function (k) { return storeIdx[k].city; })
        : (await q("SELECT city FROM city_stats")).map(function (r) { return r.city; });
      raws.forEach(function (c) {
        var key = String(c);
        if (seen[key]) return;
        seen[key] = 1;
        var g = cityGroup(c);
        (cityRawCache[g] = cityRawCache[g] || []).push(c);
      });
    }
    return cityRawCache[city] || [];
  }

  function storeNote(r) {
    var out = [];
    if (r.notes) out.push(r.notes);
    var cd = cityDisplay(r.city);
    if (cd[1]) out.push(cd[1]);
    return { city: cd[0], note: out.filter(function (v, i, a) { return a.indexOf(v) === i; }).join("; ") };
  }
  // סניף שאין לו שורה בטבלת stores = הרשת לא מפרסמת קובץ סניפים
  function branchFrom(r) {
    if (r.store_name == null && r.city == null) {
      return { branch: "סניף " + r.store_id, city: UNKNOWN, address: UNKNOWN, note: NOTE_NO_STORE_FILE };
    }
    var sn = storeNote(r);
    return { branch: r.store_name || ("סניף " + r.store_id), city: sn.city,
             address: r.address || UNKNOWN, note: sn.note };
  }

  function pickNamed(branches, price) {
    var tied = branches.filter(function (b) { return b.price === price; });
    for (var i = 0; i < tied.length; i++) {
      if (tied[i].city !== UNKNOWN) return tied[i];
    }
    return tied[0];
  }

  function productBrief(row) {
    return {
      barcode: row.barcode, name: row.name || UNKNOWN, tint: tintFor(row.barcode),
      min: money(row.min_price), max: money(row.max_price), median: money(row.median),
      gap_pct: Math.round(row.gap_pct * 10) / 10,
      gap_shekel: money(row.max_price - row.min_price),
      stores: row.n_stores, chains: row.n_chains,
      min_chain: row.min_chain, max_chain: row.max_chain,
      min_date: row.min_date, max_date: row.max_date
    };
  }

  async function storeMeta(chain, storeId) {
    var r = lookupStore(chain, storeId);
    if (r === null && !storeIdx) {
      r = (await q("SELECT store_name, city, address, notes FROM stores WHERE chain=? AND store_id=?",
                   [chain, storeId]))[0];
    }
    if (!r) return { branch: "סניף " + storeId, city: UNKNOWN, address: UNKNOWN, note: NOTE_NO_STORE_FILE };
    var sn = storeNote(r);
    return { branch: r.store_name || ("סניף " + storeId), city: sn.city,
             address: r.address || UNKNOWN, note: sn.note };
  }

  async function dataMeta() {
    if (metaCache) return metaCache;
    if (pre.meta) { metaCache = pre.meta; return metaCache; }
    var kv = {};
    (await q("SELECT key, value FROM app_meta")).forEach(function (r) { kv[r.key] = r.value; });
    var cutoff = freshCutoff();
    var chains = (await q("SELECT * FROM chain_stats ORDER BY chain")).map(function (r) {
      return { name: r.chain, stores: r.stores, rows: r.rows, from: r.date_min, to: r.date_max,
               stale: (r.date_max || "") < cutoff,
               note: r.has_store_file ? "" : NOTE_NO_STORE_FILE };
    });
    var unknown = (await q("SELECT stores n FROM city_stats WHERE city=?", [UNKNOWN]))[0];
    var nprod = (await q("SELECT COUNT(*) n FROM product_stats"))[0].n;
    metaCache = {
      latest_date: kv.latest_date, fresh_from: cutoff, fresh_days: FRESH_DAYS,
      stores_today: parseInt(kv.stores_today || "0", 10),
      stores_total: parseInt(kv.stores_total || "0", 10),
      products: nprod, price_rows: parseInt(kv.price_rows || "0", 10),
      chains: chains, index_built_at: kv.index_built_at || null,
      unknown_city_stores: unknown ? unknown.n : 0
    };
    return metaCache;
  }

  async function cityList() {
    if (pre.cities) return pre.cities;
    var counts = {};
    (await q("SELECT city, stores n FROM city_stats")).forEach(function (r) {
      var name = cityGroup(r.city);
      counts[name] = (counts[name] || 0) + r.n;
    });
    var out = Object.keys(counts).filter(function (c) { return c !== UNKNOWN; })
      .sort(function (a, b) { return counts[b] - counts[a]; })
      .map(function (c) { return { name: c, stores: counts[c] }; });
    if (counts[UNKNOWN]) out.push({ name: UNKNOWN, stores: counts[UNKNOWN] });
    return out;
  }

  function ftsQuery(text) {
    // מילים בנות תו אחד לא מצמצמות את החיפוש אבל עולות ביוקר כקידומת
    var words = String(text).split(/[^\wא-ת%]+/).filter(function (w) { return w.length > 1; });
    if (!words.length) words = String(text).split(/[^\wא-ת%]+/).filter(Boolean);
    return words.map(function (w) { return '"' + w + '"*'; }).join(" ");
  }

  async function searchProducts(text, limit) {
    text = String(text || "").trim();
    limit = limit || 30;
    if (!text) return [];
    if (/^\d{4,}$/.test(text)) {
      // טווח ולא LIKE, כדי שהאינדקס על הברקוד ישמש בפועל
      var hi = text.slice(0, -1) + String.fromCharCode(text.charCodeAt(text.length - 1) + 1);
      var byCode = await q("SELECT * FROM product_stats WHERE barcode >= ? AND barcode < ? " +
                           "ORDER BY n_stores DESC LIMIT ?", [text, hi, limit]);
      if (byCode.length) return byCode.map(productBrief);
    }
    var rows = [];
    try {
      // בלי ORDER BY. השורות הוכנסו לאינדקס לפי מספר סניפים יורד, ו-FTS5
      // מחזיר לפי סדר ההכנסה, ולכן LIMIT מחזיר כבר את הנפוצים ביותר ועוצר שם.
      // עם ORDER BY, המנוע נאלץ לקרוא את כל רשימת ההתאמות - עשרות מגה למילה נפוצה.
      rows = await q("SELECT barcode, name, min_price, max_price, median, gap_pct, n_stores, " +
                     "n_chains, min_chain, max_chain, min_date, max_date FROM product_fts " +
                     "WHERE product_fts MATCH ? LIMIT ?", [ftsQuery(text), limit]);
      rows.sort(function (a, b) { return b.n_stores - a.n_stores; });
    } catch (e) { rows = []; }
    if (!rows.length) {
      var words = text.split(/\s+/).filter(Boolean);
      var where = words.map(function () { return "name LIKE ?"; }).join(" AND ") || "name LIKE ?";
      var params = words.length ? words.map(function (w) { return "%" + w + "%"; }) : ["%" + text + "%"];
      rows = await q("SELECT * FROM product_stats WHERE " + where + " ORDER BY n_stores DESC LIMIT ?",
                     params.concat([limit]));
    }
    return rows.map(productBrief);
  }

  async function home() {
    var meta = await dataMeta();
    if (pre.home) return Object.assign({}, pre.home, { meta: meta });
    var popular = (await q(
      "SELECT * FROM product_stats WHERE name IS NOT NULL AND name<>'' AND n_stores>=300 AND gap_pct>0 " +
      "ORDER BY n_stores DESC LIMIT 60")).map(productBrief);
    popular.sort(function (a, b) { return b.gap_pct - a.gap_pct; });
    var top = popular.slice(0, 8);

    // כל הסדרות של שמונת המוצרים בשאילתה אחת, במקום שאילתה לכל מוצר
    var codes = top.map(function (p) { return p.barcode; });
    var byCode = {};
    if (codes.length) {
      (await q("SELECT barcode, date, median FROM market_daily WHERE barcode IN (" +
               placeholders(codes.length) + ") ORDER BY barcode, date", codes)).forEach(function (r) {
        (byCode[r.barcode] = byCode[r.barcode] || []).push(money(r.median));
      });
    }
    top.forEach(function (p) {
      var v = byCode[p.barcode] || [];
      p.spark = v.length > 1 ? v.slice(-6) : [];
    });

    var deal = null;
    if (top.length) {
      var row = (await q("SELECT * FROM product_stats WHERE barcode=?", [top[0].barcode]))[0];
      deal = Object.assign({}, top[0], {
        min_store: await storeMeta(row.min_chain, row.min_store),
        max_store: await storeMeta(row.max_chain, row.max_store)
      });
    }

    // הטיקר: שולפים את כל הסדרות של המוצרים במעקב פעם אחת ומחשבים בזיכרון
    var mp = await q("SELECT mp.barcode, mp.rank, ps.name FROM market_products mp " +
                     "JOIN product_stats ps ON ps.barcode=mp.barcode ORDER BY mp.rank LIMIT 14");
    var tcodes = mp.map(function (r) { return r.barcode; });
    var series = {};
    if (tcodes.length) {
      (await q("SELECT barcode, date, median FROM market_daily WHERE barcode IN (" +
               placeholders(tcodes.length) + ") ORDER BY barcode, date", tcodes)).forEach(function (r) {
        (series[r.barcode] = series[r.barcode] || []).push(r);
      });
    }
    var ticker = mp.map(function (r) {
      var v = series[r.barcode] || [];
      var last = v[v.length - 1], prev = v[v.length - 2];
      if (!last) return null;
      return { barcode: r.barcode, name: r.name, price: money(last.median),
               change: prev ? pct(last.median, prev.median) : null, date: last.date };
    }).filter(Boolean);

    return { meta: meta, popular: top, deal: deal, ticker: ticker,
             quick: popular.slice(0, 5).map(function (p) {
               return { barcode: p.barcode, name: p.name, tint: p.tint };
             }) };
  }

  async function product(o) {
    var row = (await q("SELECT * FROM product_stats WHERE barcode=?", [o.barcode]))[0];
    if (!row) return { error: "המוצר לא נמצא" };
    var where = ["pr.barcode = ?"], params = [o.barcode];
    if (!o.includeOld) { where.push("pr.date >= ?"); params.push(freshCutoff()); }
    if (o.chains && o.chains.length) {
      where.push("pr.chain IN (" + placeholders(o.chains.length) + ")");
      params = params.concat(o.chains);
    }
    var raw = o.city ? await cityRawValues(o.city) : null;
    if (raw) {
      if (!raw.length) raw = [" none"];
      where.push("s.city IN (" + placeholders(raw.length) + ")");
      params = params.concat(raw);
    }
    var rows;
    if (storeIdx) {
      // מסננים לפי עיר בזיכרון במקום לצרף את טבלת הסניפים במסד
      var cityWhere = where.filter(function (w) { return w.indexOf("s.city") < 0; });
      var cityParams = params.slice(0, params.length - (raw ? raw.length : 0));
      rows = (await q("SELECT pr.price, pr.chain, pr.store_id, pr.date FROM prices pr WHERE " +
                      cityWhere.join(" AND ") + " ORDER BY pr.price", cityParams)).map(function (r) {
        var st = lookupStore(r.chain, r.store_id) || {};
        return { price: r.price, chain: r.chain, store_id: r.store_id, date: r.date,
                 store_name: st.store_name === undefined ? null : st.store_name,
                 city: st.city === undefined ? null : st.city,
                 address: st.address === undefined ? null : st.address,
                 notes: st.notes === undefined ? null : st.notes };
      });
      if (raw) {
        var ok = {};
        raw.forEach(function (c) { ok[String(c)] = 1; });
        rows = rows.filter(function (r) { return ok[String(r.city)]; });
      }
    } else {
      rows = await q(
        "SELECT pr.price, pr.chain, pr.store_id, pr.date, s.store_name, s.city, s.address, s.notes " +
        "FROM prices pr LEFT JOIN stores s ON s.chain=pr.chain AND s.store_id=pr.store_id " +
        "WHERE " + where.join(" AND ") + " ORDER BY pr.price", params);
    }

    // המסד הענני מכיל רק מחירים מחלון הטריות, ולכן אין מחירים ישנים להשמיט
    var excludedOld = 0;

    var branches = rows.map(function (r) {
      var b = branchFrom(r);
      return { price: money(r.price), chain: r.chain, store_id: r.store_id, branch: b.branch,
               city: b.city, address: b.address, date: r.date, note: b.note };
    });

    var prices = branches.map(function (b) { return b.price; });
    var stats = null;
    if (prices.length) {
      var ds = {};
      branches.forEach(function (b) { ds[b.date] = 1; });
      stats = {
        min: prices[0], max: prices[prices.length - 1], median: money(median(prices)),
        avg: money(prices.reduce(function (a, b) { return a + b; }, 0) / prices.length),
        gap_pct: prices[0] ? Math.round((prices[prices.length - 1] - prices[0]) / prices[0] * 1000) / 10 : 0,
        gap_shekel: money(prices[prices.length - 1] - prices[0]),
        count: prices.length,
        // בין סניפים שחולקים בדיוק את אותו מחיר, מציגים אחד שיש לו עיר.
        // כולם נכונים באותה מידה, ולמשתמש עדיף אחד שאפשר להגיע אליו.
        min_branch: pickNamed(branches, prices[0]),
        max_branch: pickNamed(branches, prices[prices.length - 1]),
        min_ties: branches.filter(function (b) { return b.price === prices[0]; }).length,
        max_ties: branches.filter(function (b) { return b.price === prices[prices.length - 1]; }).length,
        dates: Object.keys(ds).sort()
      };
    }

    var byChain = {};
    branches.forEach(function (b) { (byChain[b.chain] = byChain[b.chain] || []).push(b.price); });
    var chainRows = Object.keys(byChain).map(function (c) {
      var v = byChain[c];
      return { chain: c, avg: money(v.reduce(function (a, b) { return a + b; }, 0) / v.length),
               min: money(Math.min.apply(null, v)), max: money(Math.max.apply(null, v)), stores: v.length };
    }).sort(function (a, b) { return a.avg - b.avg; });
    chainRows.forEach(function (c, i) { c.color = heatColor(i, chainRows.length); });

    var byCity = {};
    branches.forEach(function (b) {
      if (b.city === UNKNOWN) return;
      (byCity[b.city] = byCity[b.city] || []).push(b.price);
    });
    var cityRows = Object.keys(byCity).map(function (c) {
      var v = byCity[c];
      return { city: c, min: money(Math.min.apply(null, v)),
               avg: money(v.reduce(function (a, b) { return a + b; }, 0) / v.length), stores: v.length };
    }).sort(function (a, b) { return a.min - b.min; });
    cityRows.forEach(function (c, i) { c.color = heatColor(i, cityRows.length); });

    var history = (await q("SELECT date, median, min_price, max_price, n_stores FROM market_daily " +
                           "WHERE barcode=? ORDER BY date", [o.barcode])).map(function (r) {
      return { date: r.date, median: money(r.median), min: money(r.min_price),
               max: money(r.max_price), stores: r.n_stores };
    });
    var allChains;
    if ((!o.chains || !o.chains.length) && !o.city) {
      var seen = {};
      branches.forEach(function (b) { seen[b.chain] = 1; });
      allChains = Object.keys(seen).sort();
    } else {
      allChains = (await q("SELECT DISTINCT chain FROM prices WHERE barcode=? ORDER BY chain",
                           [o.barcode])).map(function (r) { return r.chain; });
    }

    return {
      product: productBrief(row), stats: stats, branches: branches.slice(0, 400),
      branch_count: branches.length, chain_rows: chainRows, city_rows: cityRows,
      history: history, all_chains: allChains, excluded_old: excludedOld,
      no_city_count: branches.filter(function (b) { return b.city === UNKNOWN; }).length,
      meta: await dataMeta()
    };
  }

  async function market(barcode) {
    // רשימת המוצרים במעקב זהה לכולם ומחושבת מראש; רק המוצר הנבחר נטען לפי הצורך
    if (pre.market && pre.market.items) {
      var meta0 = await dataMeta();
      var chosen0 = pre.market.items.filter(function (i) { return i.barcode === barcode; })[0];
      if (!barcode || !chosen0 || (pre.market.selected && pre.market.selected.barcode === barcode)) {
        return Object.assign({}, pre.market, { meta: meta0 });
      }
      var sel0 = Object.assign({}, chosen0);
      sel0.series = (await q("SELECT date, median, min_price, max_price, n_stores FROM market_daily " +
                             "WHERE barcode=? ORDER BY date", [barcode])).map(function (r) {
        return { date: r.date, median: money(r.median), min: money(r.min_price),
                 max: money(r.max_price), stores: r.n_stores };
      });
      sel0.today = productBrief((await q("SELECT * FROM product_stats WHERE barcode=?", [barcode]))[0]);
      var dep0 = (await q("SELECT chain, AVG(price) a, MIN(price) mn, MAX(price) mx, COUNT(*) n " +
                          "FROM prices WHERE barcode=? AND date>=? GROUP BY chain ORDER BY a",
                          [barcode, freshCutoff()])).map(function (r) {
        return { chain: r.chain, avg: money(r.a), min: money(r.mn), max: money(r.mx), stores: r.n };
      });
      dep0.forEach(function (d, i) { d.color = heatColor(i, dep0.length); });
      sel0.depth = dep0;
      return Object.assign({}, pre.market, { selected: sel0, meta: meta0 });
    }
    var mp = await q("SELECT mp.barcode, mp.symbol, mp.rank, ps.name, ps.n_stores FROM market_products mp " +
                     "JOIN product_stats ps ON ps.barcode=mp.barcode ORDER BY mp.rank");
    var codes = mp.map(function (r) { return r.barcode; });
    var series = {};
    if (codes.length) {
      (await q("SELECT barcode, date, median, min_price, max_price, n_stores FROM market_daily " +
               "WHERE barcode IN (" + placeholders(codes.length) + ") ORDER BY barcode, date",
               codes)).forEach(function (r) {
        (series[r.barcode] = series[r.barcode] || []).push(r);
      });
    }
    var items = mp.map(function (r) {
      var v = series[r.barcode] || [];
      if (!v.length) return null;
      var last = v[v.length - 1], prev = v[v.length - 2];
      return { barcode: r.barcode, symbol: r.symbol, name: r.name, stores: r.n_stores,
               price: money(last.median), date: last.date,
               prev: prev ? money(prev.median) : null, prev_date: prev ? prev.date : null,
               change: prev ? pct(last.median, prev.median) : null,
               spark: v.slice(-30).map(function (s) { return money(s.median); }) };
    }).filter(Boolean);

    var sel = null;
    if (items.length) {
      var chosen = items.filter(function (i) { return i.barcode === barcode; })[0] || items[0];
      sel = Object.assign({}, chosen);
      sel.series = (series[chosen.barcode] || []).map(function (r) {
        return { date: r.date, median: money(r.median), min: money(r.min_price),
                 max: money(r.max_price), stores: r.n_stores };
      });
      sel.today = productBrief((await q("SELECT * FROM product_stats WHERE barcode=?", [chosen.barcode]))[0]);
      var depth = (await q("SELECT chain, AVG(price) a, MIN(price) mn, MAX(price) mx, COUNT(*) n FROM prices " +
                           "WHERE barcode=? AND date>=? GROUP BY chain ORDER BY a",
                           [chosen.barcode, freshCutoff()])).map(function (r) {
        return { chain: r.chain, avg: money(r.a), min: money(r.mn), max: money(r.mx), stores: r.n };
      });
      depth.forEach(function (d, i) { d.color = heatColor(i, depth.length); });
      sel.depth = depth;
    }
    var movers = items.filter(function (i) { return i.change != null; });
    return {
      items: items, selected: sel,
      losers: movers.slice().sort(function (a, b) { return a.change - b.change; }).slice(0, 3),
      gainers: movers.slice().sort(function (a, b) { return b.change - a.change; }).slice(0, 3),
      meta: await dataMeta()
    };
  }

  async function basketAnalysis(entries, city, includeOld) {
    var wanted = {};
    entries.forEach(function (e) {
      var code = String(e.barcode || "").trim();
      if (!code) return;
      wanted[code] = (wanted[code] || 0) + Math.max(1, parseInt(e.qty, 10) || 1);
    });
    var codes = Object.keys(wanted);
    if (!codes.length) return { error: "הסל ריק" };

    var where = ["pr.barcode IN (" + placeholders(codes.length) + ")"];
    var params = codes.slice();
    if (!includeOld) { where.push("pr.date >= ?"); params.push(freshCutoff()); }
    var raw = city ? await cityRawValues(city) : null;
    if (raw) {
      if (!raw.length) raw = [" none"];
      where.push("s.city IN (" + placeholders(raw.length) + ")");
      params = params.concat(raw);
    }
    var rows;
    if (storeIdx) {
      var cw = where.filter(function (w) { return w.indexOf("s.city") < 0; });
      var cp = params.slice(0, params.length - (raw ? raw.length : 0));
      rows = (await q("SELECT pr.chain, pr.store_id, pr.barcode, pr.price, pr.date FROM prices pr WHERE " +
                      cw.join(" AND "), cp)).map(function (r) {
        var st = lookupStore(r.chain, r.store_id) || {};
        return { chain: r.chain, store_id: r.store_id, barcode: r.barcode, price: r.price, date: r.date,
                 store_name: st.store_name === undefined ? null : st.store_name,
                 city: st.city === undefined ? null : st.city,
                 address: st.address === undefined ? null : st.address,
                 notes: st.notes === undefined ? null : st.notes };
      });
      if (raw) {
        var ok2 = {};
        raw.forEach(function (c) { ok2[String(c)] = 1; });
        rows = rows.filter(function (r) { return ok2[String(r.city)]; });
      }
    } else {
      rows = await q("SELECT pr.chain, pr.store_id, pr.barcode, pr.price, pr.date, " +
                     "s.store_name, s.city, s.address, s.notes FROM prices pr " +
                     "LEFT JOIN stores s ON s.chain=pr.chain AND s.store_id=pr.store_id " +
                     "WHERE " + where.join(" AND "), params);
    }

    var stores = {}, info = {};
    rows.forEach(function (r) {
      var key = r.chain + " " + r.store_id;
      var cur = stores[key] = stores[key] || {};
      var prev = cur[r.barcode];
      if (!prev || r.price < prev[0]) cur[r.barcode] = [r.price, r.date];
      if (!info[key]) {
        var b = branchFrom(r);
        info[key] = { chain: r.chain, store_id: r.store_id, branch: b.branch,
                      city: b.city, address: b.address, note: b.note };
      }
    });

    var names = {};
    (await q("SELECT barcode, name, min_price, max_price FROM product_stats WHERE barcode IN (" +
             placeholders(codes.length) + ")", codes)).forEach(function (r) {
      names[r.barcode] = { name: r.name || UNKNOWN, min: r.min_price, max: r.max_price };
    });

    var keys = Object.keys(stores);
    var available = codes.filter(function (c) {
      return keys.some(function (k) { return stores[k][c] !== undefined; });
    });
    var missing = codes.filter(function (c) { return available.indexOf(c) < 0; });

    function total(key, subset) {
      return subset.reduce(function (a, b) { return a + stores[key][b][0] * wanted[b]; }, 0);
    }
    var full = keys.filter(function (k) {
      return available.every(function (b) { return stores[k][b] !== undefined; });
    });
    var ranked;
    if (full.length) {
      ranked = full.sort(function (a, b) { return total(a, available) - total(b, available); });
    } else {
      ranked = keys.sort(function (a, b) {
        var ca = available.filter(function (x) { return stores[a][x] !== undefined; });
        var cb = available.filter(function (x) { return stores[b][x] !== undefined; });
        if (cb.length !== ca.length) return cb.length - ca.length;
        return total(a, ca) - total(b, cb);
      });
    }
    var bestList = ranked.slice(0, 12).map(function (k) {
      var have = available.filter(function (b) { return stores[k][b] !== undefined; });
      var ds = {};
      have.forEach(function (b) { ds[stores[k][b][1]] = 1; });
      return Object.assign({}, info[k], { total: money(total(k, have)), items: have.length,
                                          complete: have.length === available.length,
                                          dates: Object.keys(ds).sort() });
    });

    var perItem = {};
    available.forEach(function (b) {
      var bk = null, bp = Infinity;
      keys.forEach(function (k) {
        var e = stores[k][b];
        if (e && e[0] < bp) { bp = e[0]; bk = k; }
      });
      perItem[b] = { price: money(bp), store: bk, date: stores[bk][b][1] };
    });
    var splitTotal = money(Object.keys(perItem).reduce(function (a, b) {
      return a + perItem[b].price * wanted[b];
    }, 0));
    var byStore = {};
    Object.keys(perItem).forEach(function (b) {
      var k = perItem[b].store;
      (byStore[k] = byStore[k] || []).push({ barcode: b, name: (names[b] || {}).name || UNKNOWN,
        price: perItem[b].price, qty: wanted[b], date: perItem[b].date, tint: tintFor(b) });
    });
    var split = Object.keys(byStore).map(function (k) {
      return { store: info[k], items: byStore[k],
               total: money(byStore[k].reduce(function (a, i) { return a + i.price * i.qty; }, 0)) };
    }).sort(function (a, b) { return b.total - a.total; });

    var chainBest = {};
    keys.forEach(function (k) {
      if (!available.every(function (b) { return stores[k][b] !== undefined; })) return;
      var t = total(k, available), ch = info[k].chain;
      if (!chainBest[ch] || t < chainBest[ch].total) {
        chainBest[ch] = { chain: ch, total: money(t), store: info[k] };
      }
    });
    var chainList = Object.keys(chainBest).map(function (c) { return chainBest[c]; })
      .sort(function (a, b) { return a.total - b.total; });
    chainList.forEach(function (c, i) { c.color = heatColor(i, chainList.length); });

    var itemsOut = codes.map(function (b) {
      var cands = [];
      keys.forEach(function (k) { if (stores[k][b]) cands.push(stores[k][b][0]); });
      cands.sort(function (x, y) { return x - y; });
      var ns = names[b] || {};
      return { barcode: b, name: ns.name || UNKNOWN, qty: wanted[b], tint: tintFor(b),
               min: cands.length ? money(cands[0]) : null,
               max: cands.length ? money(cands[cands.length - 1]) : null,
               found: cands.length > 0, stores: cands.length,
               national_min: ns.min != null ? money(ns.min) : null,
               national_max: ns.max != null ? money(ns.max) : null };
    });

    var best = bestList[0] || null;
    var bestItems = [];
    if (best) {
      var bk2 = best.chain + " " + best.store_id;
      bestItems = codes.map(function (b) {
        var e = stores[bk2][b];
        return { barcode: b, name: (names[b] || {}).name || UNKNOWN, qty: wanted[b],
                 price: e ? money(e[0]) : null, date: e ? e[1] : null,
                 total: e ? money(e[0] * wanted[b]) : null };
      });
    }

    return { items: itemsOut, missing: missing, available: available.length, best: best,
             best_items: bestItems, best_list: bestList, split: split, split_total: splitTotal,
             split_saving: best ? money(best.total - splitTotal) : 0,
             chain_totals: chainList, city: city || "", store_count: keys.length,
             meta: await dataMeta() };
  }

  var RECEIPT_LINE = /^\s*(?:(\d+(?:[.,]\d+)?)\s*[xX*×]\s*)?(.+?)(?:\s+(\d+(?:[.,]\d{1,2})?))?\s*(?:₪|ש"ח|שח)?\s*$/;

  function parseReceipt(text) {
    var out = [];
    String(text || "").split(/\r?\n/).forEach(function (raw) {
      var line = raw.trim();
      if (!line || line.length < 2) return;
      if (/^[\d\s.,:\-*=₪]+$/.test(line)) return;
      var m = RECEIPT_LINE.exec(line);
      if (!m) { out.push({ raw: line, desc: line, qty: 1, paid: null }); return; }
      var body = (m[2] || "").replace(/^[\s.\-]+|[\s.\-]+$/g, "");
      var barcode = null;
      var bm = /\b(\d{8,14})\b/.exec(body);
      if (bm) {
        barcode = bm[1];
        body = (body.slice(0, bm.index) + " " + body.slice(bm.index + bm[0].length)).trim();
      }
      out.push({ raw: line, desc: body || line, barcode: barcode,
                 qty: m[1] ? parseFloat(m[1].replace(",", ".")) : 1,
                 paid: m[3] ? parseFloat(m[3].replace(",", ".")) : null });
    });
    return out;
  }

  async function receipt(text, city) {
    var lines = parseReceipt(text), matched = [], unmatched = [];
    // כל השורות מזוהות במקביל. ה-worker עדיין מריץ שאילתה אחת בכל רגע,
    // אבל כך לא משלמים סבב הודעות שלם בין שורה לשורה.
    var resolved = await Promise.all(lines.map(async function (ln) {
      var prod = null;
      if (ln.barcode) {
        var r = (await q("SELECT * FROM product_stats WHERE barcode=?", [ln.barcode]))[0];
        if (r) prod = productBrief(r);
      }
      if (!prod) {
        var hits = await searchProducts(ln.desc, 3);
        if (hits.length) {
          prod = hits[0];
          ln.ambiguous = hits.slice(1).map(function (h) { return h.name; });
        }
      }
      return { ln: ln, prod: prod };
    }));
    resolved.forEach(function (x) {
      if (x.prod) matched.push(Object.assign({}, x.ln, { product: x.prod }));
      else unmatched.push(x.ln);
    });
    var analysis = null;
    if (matched.length) {
      analysis = await basketAnalysis(matched.map(function (m) {
        return { barcode: m.product.barcode, qty: Math.max(1, Math.round(m.qty)) };
      }), city);
      var cheapest = {};
      (analysis.split || []).forEach(function (s) {
        s.items.forEach(function (it) { cheapest[it.barcode] = it; });
      });
      analysis.cheapest_by_item = cheapest;
      var bsp = {};
      (analysis.best_items || []).forEach(function (it) {
        if (it.price != null) bsp[it.barcode] = { price: it.price, date: it.date };
      });
      analysis.best_store_prices = bsp;
    }
    var paid = matched.reduce(function (a, m) { return a + (m.paid || 0) * m.qty; }, 0);
    return { matched: matched, unmatched: unmatched,
             paid_total: paid ? money(paid) : null,
             paid_known: matched.filter(function (m) { return m.paid != null; }).length,
             analysis: analysis, meta: await dataMeta() };
  }

  return {
    mode: "sqlite",
    init: async function (onProgress) {
      if (onProgress) onProgress("טוען את מנוע הנתונים…");
      try {
        cbs = await (await fetch(abs(cfg.cbsUrl || "cities_cbs.json"))).json();
      } catch (e) { cbs = {}; }
      buildAlias();
      if (onProgress) onProgress("מתחבר למסד הנתונים…");
      worker = await window.createDbWorker(
        [{ from: "inline", config: { serverMode: "full", url: abs(cfg.dbUrl),
                                     requestChunkSize: cfg.chunkSize || 4096 } }],
        abs(cfg.workerUrl || "vendor/sqlite.worker.js"),
        abs(cfg.wasmUrl || "vendor/sql-wasm.wasm"));
      // חלון הטריות נמדד מהתאריך האחרון שבנתונים, לא מהיום, כדי שהאתר
      // לא יתרוקן אם לא הריצו עדכון כמה ימים.
      var rows = await q("SELECT value FROM app_meta WHERE key='latest_date'");
      latestDate = (rows[0] && rows[0].value) || new Date().toISOString().slice(0, 10);
      // ערכים שחושבו מראש בזמן בניית המסד: חוסכים סריקה של אלפי דפים בכל ביקור
      try {
        (await q("SELECT key, value FROM precomputed")).forEach(function (r) {
          try { pre[r.key] = JSON.parse(r.value); } catch (e) {}
        });
      } catch (e) { pre = {}; }
      if (pre.stores) buildStoreIdx();
    },
    meta: async function () { return { meta: await dataMeta(), cities: await cityList() }; },
    home: home,
    search: async function (qs, limit) { return { query: qs, results: await searchProducts(qs, limit) }; },
    product: product,
    market: market,
    basket: function (items, city, includeOld) { return basketAnalysis(items, city || null, !!includeOld); },
    receipt: function (text, city) { return receipt(text, city || null); }
  };
}

// ------------------------------------------------------------------ factory
window.MehironData = function (cfg) {
  cfg = cfg || window.MEHIRON_CONFIG || {};
  return cfg.mode === "sqlite" ? SqliteApi(cfg) : ServerApi();
};
})();
