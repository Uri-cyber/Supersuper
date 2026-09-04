/* מחירון - לוגיקת האפליקציה.
   כל המספרים מגיעים מהשרת, שקורא את הקבצים שהרשתות פרסמו. אין נתוני דמה. */
(function () {
"use strict";

// ------------------------------------------------------------------ state
var S = {
  screen: "home",
  query: "",
  focused: false,
  suggestions: [],
  searchedFor: "",
  searchError: null,
  home: null,
  product: null,
  productBarcode: null,
  city: "",
  chains: null,           // null = כל הרשתות
  includeOld: false,
  cart: [],               // [{barcode,name,qty,tint}]
  cartData: null,
  market: null,
  marketBarcode: null,
  range: "1M",
  scanPhase: "idle",
  scanText: "",
  scanResult: null,
  meta: null,
  cities: [],
  geo: {},
  burst: false,
  filterOpen: (typeof window !== "undefined" && window.innerWidth > 820),
  mx: 0, my: 0,
  toast: null
};

var HEAT = ["#1fb85a", "#7fd63a", "#ffcb3d", "#ff9a3d", "#ff6a4d", "#ff4d4d"];
var UNKNOWN = "לא ידוע";
var LS_CART = "mehiron.cart";
var LS_CITY = "mehiron.city";

// ------------------------------------------------------------------ utils
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function nis(v, d) {
  if (v == null || isNaN(v)) return "—";
  return Number(v).toLocaleString("he-IL", { minimumFractionDigits: d == null ? 2 : d, maximumFractionDigits: d == null ? 2 : d });
}
function num(v) { return v == null || isNaN(v) ? "—" : Number(v).toLocaleString("he-IL"); }
function pctStr(v) {
  if (v == null || isNaN(v)) return "—";
  var s = Number(v).toFixed(1).replace(/\.0$/, "");
  return (v > 0 ? "+" : "") + s + "%";
}
function heat(i, n) {
  if (n <= 1) return HEAT[0];
  return HEAT[Math.round(i / (n - 1) * (HEAT.length - 1))];
}
function dateHe(d) {
  if (!d) return UNKNOWN;
  var p = String(d).split("-");
  return p.length === 3 ? p[2] + "." + p[1] + "." + p[0] : d;
}
var API = null;   // נקבע ב-boot לפי config.js
function debounce(fn, ms) {
  var t; return function () { var a = arguments, c = this; clearTimeout(t); t = setTimeout(function () { fn.apply(c, a); }, ms); };
}
function saveCart() {
  try { localStorage.setItem(LS_CART, JSON.stringify(S.cart)); } catch (e) {}
}
function loadCart() {
  try {
    var v = JSON.parse(localStorage.getItem(LS_CART) || "[]");
    if (Array.isArray(v)) S.cart = v;
    S.city = localStorage.getItem(LS_CITY) || "";
  } catch (e) {}
}
function cartCount() { return S.cart.reduce(function (a, i) { return a + (i.qty || 1); }, 0); }
function toast(msg) {
  S.toast = msg;
  render();
  setTimeout(function () { if (S.toast === msg) { S.toast = null; render(); } }, 2600);
}

// הערה על נתונים חסרים - מוצגת ליד כל סניף שחסר לו מידע
function noteChip(note) {
  if (!note) return "";
  return '<span class="small" style="color:var(--muted);font-weight:600" title="' + esc(note) + '">ⓘ ' + esc(note) + "</span>";
}

// ------------------------------------------------------------------ count-up
// לא מסתמך על requestAnimationFrame בלבד: בלשונית מוסתרת קופץ ישר ליעד.
var anims = {};
function countUp(key, target, cb) {
  var a = anims[key];
  var from = a ? a.value : 0;
  if (document.hidden) { anims[key] = { value: target }; cb(target); return; }
  var start = Date.now();
  if (a && a.timer) clearInterval(a.timer);
  var rec = anims[key] = { value: from, timer: null };
  rec.timer = setInterval(function () {
    var t = Math.min(1, (Date.now() - start) / 900);
    var e = 1 - Math.pow(1 - t, 3);
    rec.value = from + (target - from) * e;
    cb(rec.value);
    if (t >= 1) { clearInterval(rec.timer); rec.timer = null; rec.value = target; }
  }, 30);
}
function runCountUps(root) {
  (root || document).querySelectorAll("[data-count]").forEach(function (el) {
    var target = parseFloat(el.getAttribute("data-count"));
    var dec = parseInt(el.getAttribute("data-dec") || "2", 10);
    var key = el.getAttribute("data-key") || Math.random();
    countUp(key, target, function (v) { el.textContent = nis(v, dec); });
  });
}

// ------------------------------------------------------------------ header
function header() {
  var c = cartCount();
  function tab(id, label, icon, extra) {
    return '<button class="tab' + (S.screen === id ? " on" : "") + '" data-go="' + id + '">' +
      (icon ? '<span style="font-size:15px">' + icon + "</span>" : "") + label + (extra || "") + "</button>";
  }
  return '<header class="hdr">' +
    '<div class="brand" data-go="home"><div class="logo">₪</div>' +
    '<div class="wordmark">מחירון</div>' +
    '<div class="tagline">כל סניף. כל מחיר. כל יום.</div></div>' +
    '<nav class="nav">' +
      tab("home", "חיפוש") +
      tab("scan", "סרוק קבלה", "▦") +
      tab("market", "בורסת המחירים", "📈") +
      tab("cart", "הסל שלי", "", ' <span class="badge-count">' + c + "</span>") +
    "</nav></header>";
}

function mobileNav() {
  var c = cartCount();
  function t(id, label, icon) {
    return '<button class="' + (S.screen === id ? "on" : "") + '" data-go="' + id + '"><span style="font-size:17px">' + icon + "</span>" + label + "</button>";
  }
  return '<nav class="mob-nav">' + t("home", "חיפוש", "⌕") + t("market", "בורסה", "📈") +
    t("scan", "סרוק", "▦") + t("cart", "הסל" + (c ? " (" + c + ")" : ""), "🛒") + "</nav>";
}

function tape() {
  var items = (S.home && S.home.ticker) || [];
  if (!items.length) return "";
  function one(t) {
    var col = t.change == null || t.change === 0 ? "var(--muted-dark)"
              : (t.change < 0 ? "var(--green)" : "var(--red)");
    var arrow = t.change == null ? "•" : (t.change < 0 ? "▼" : (t.change > 0 ? "▲" : "="));
    var chg = t.change == null ? "אין השוואה"
              : (t.change === 0 ? "= ללא שינוי" : arrow + " " + Math.abs(t.change).toFixed(1) + "%");
    return '<span class="tape-item" data-open="' + esc(t.barcode) + '">' +
      '<span class="tape-delta" style="color:' + col + '">' + esc(chg) + "</span>" +
      esc(t.name) + " · " + nis(t.price) + " ₪</span>";
  }
  var html = items.map(one).join("");
  return '<div class="tape"><div class="tape-inner">' + html + html + "</div></div>";
}

function freshnessNote() {
  if (!S.meta) return "";
  return "המחירים המוצגים הם מ־" + dateHe(S.meta.fresh_from) + " ואילך. ליד כל מחיר מופיע התאריך שבו הרשת פרסמה אותו.";
}

// ------------------------------------------------------------------ home
function suggestHtml() {
  if (!S.focused) return "";
  var q = S.query.trim();
  if (S.searchError) {
    return '<div class="suggest"><div style="padding:16px 18px;font-size:14px">' +
      'החיפוש נכשל. בדקו את החיבור ונסו שוב.' +
      '<div class="small muted" style="margin-top:6px">' + esc(S.searchError) + "</div></div></div>";
  }
  // תוצאות של מילה קודמת לא נשארות על המסך בזמן שמקלידים
  if (q && S.searchedFor !== q) {
    return '<div class="suggest"><div style="padding:16px 18px;color:var(--muted);font-size:14px">' +
      '<span class="spinner"></span> מחפש…</div></div>';
  }
  var list = S.suggestions;
  if (list.length) {
    return '<div class="suggest">' + list.map(function (s) {
      return '<div class="suggest-row" data-open="' + esc(s.barcode) + '">' +
        '<div style="display:flex;align-items:center;gap:12px;min-width:0">' +
          '<div style="width:40px;height:40px;border-radius:10px;flex:none;background:' + s.tint + '"></div>' +
          '<div style="min-width:0"><div style="font-size:16px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(s.name) + "</div>" +
          '<div class="small muted mono">' + esc(s.barcode) + "</div></div></div>" +
        '<div style="font-size:14px;color:var(--green-link);font-weight:800;white-space:nowrap">החל מ־' + nis(s.min) + " ₪</div></div>";
    }).join("") + "</div>";
  }
  if (q) {
    return '<div class="suggest"><div style="padding:16px 18px;color:var(--muted);font-size:14px">לא נמצאו מוצרים ל־"' + esc(q) + '"</div></div>';
  }
  return "";
}

// עדכון רק של רשימת ההשלמה, בלי לבנות מחדש את המסך - כדי שההקלדה לא תיקטע
function paintSuggest() {
  var box = document.getElementById("sugbox");
  if (!box) { render(); return; }
  box.innerHTML = suggestHtml();
  var sb = document.querySelector(".searchbox");
  if (sb) sb.classList.toggle("on", !!S.focused);
}

function screenHome() {
  var h = S.home;
  if (!h) return '<div class="loading"><span class="spinner"></span> טוען…</div>';
  var m = h.meta;
  var px1 = (S.mx * -30) + "px", py1 = (S.my * -20) + "px";
  var px2 = (S.mx * 40) + "px", py2 = (S.my * 30) + "px";

  var sug = '<div id="sugbox">' + suggestHtml() + "</div>";

  var deal = "";
  if (h.deal) {
    var d = h.deal;
    deal = '<section class="wrap" style="margin-top:-56px;padding-bottom:0">' +
      '<div class="deal" data-open="' + esc(d.barcode) + '">' +
      '<div class="deal-shine"></div>' +
      '<div style="position:absolute;top:-14px;right:22px;background:var(--red);border:3px solid var(--ink);color:#fff;font-size:12px;font-weight:900;padding:3px 12px;border-radius:999px;transform:rotate(-3deg)">⚡ הפער של היום</div>' +
      '<div style="flex:1 1 260px;min-width:0;display:flex;flex-direction:column;gap:4px;padding-top:6px">' +
        '<div style="font-size:13px;font-weight:700;color:var(--purple-tint)">' + num(d.stores) + " סניפים · " + num(d.chains) + " רשתות</div>" +
        '<div style="font-size:26px;font-weight:900;line-height:1.1">' + esc(d.name) + "</div>" +
        '<div style="font-size:14px;color:var(--purple-tint);font-weight:600">אותו מוצר. ' + pctStr(d.gap_pct) + " יותר יקר ב" + esc(d.max_chain) + " מאשר ב" + esc(d.min_chain) + ".</div>" +
        '<div class="small" style="color:var(--purple-tint)">הזול: ' + esc(d.min_store.branch) + ", " + esc(d.min_store.city) + " · " + dateHe(d.min_date) +
        " | היקר: " + esc(d.max_store.branch) + ", " + esc(d.max_store.city) + " · " + dateHe(d.max_date) + "</div>" +
      "</div>" +
      '<div style="display:flex;align-items:center;gap:14px" class="tnum">' +
        '<div style="background:var(--green);color:var(--ink);border:3px solid var(--ink);border-radius:16px;padding:10px 16px;text-align:center"><div style="font-size:11px;font-weight:800">' + esc(d.min_chain) + '</div><div style="font-size:30px;font-weight:900;line-height:1">' + nis(d.min) + "</div></div>" +
        '<div style="font-size:26px;font-weight:900">←</div>' +
        '<div style="background:var(--red);color:#fff;border:3px solid var(--ink);border-radius:16px;padding:10px 16px;text-align:center"><div style="font-size:11px;font-weight:800">' + esc(d.max_chain) + '</div><div style="font-size:30px;font-weight:900;line-height:1;text-decoration:line-through;text-decoration-thickness:3px">' + nis(d.max) + "</div></div>" +
      "</div></div></section>";
  }

  var pop = h.popular.map(function (p) {
    var spark = "";
    if (p.spark && p.spark.length > 1) {
      var mn = Math.min.apply(null, p.spark), mx = Math.max.apply(null, p.spark);
      var rng = (mx - mn) || 1;
      var pts = p.spark.map(function (v, i) {
        return (i / (p.spark.length - 1) * 100).toFixed(1) + "," + (22 - (v - mn) / rng * 20).toFixed(1);
      }).join(" ");
      var down = p.spark[p.spark.length - 1] <= p.spark[0];
      spark = '<svg viewBox="0 0 100 24" preserveAspectRatio="none" style="width:100%;height:24px;display:block;direction:ltr"><polyline points="' + pts + '" fill="none" stroke="' + (down ? "var(--green)" : "var(--red)") + '" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    } else {
      spark = '<div class="small muted" style="height:24px;display:flex;align-items:center">אין מספיק היסטוריה להצגת מגמה</div>';
    }
    return '<button class="pcard" data-open="' + esc(p.barcode) + '">' +
      '<div class="pimg" style="background:' + p.tint + '">' +
        '<span style="position:relative;background:#fff;padding:3px 8px;border-radius:6px;font-weight:700">אין תמונה</span>' +
        '<span style="position:absolute;top:10px;right:10px;font-size:12px;font-weight:900;color:#fff;background:var(--red);border-radius:8px;padding:4px 9px;transform:rotate(6deg)">פער ' + pctStr(p.gap_pct) + "</span></div>" +
      '<div><div class="small muted">' + num(p.stores) + " סניפים · " + num(p.chains) + ' רשתות</div><div style="font-size:16px;font-weight:800;line-height:1.3">' + esc(p.name) + "</div></div>" +
      spark +
      '<div style="display:flex;align-items:center;gap:8px;font-size:15px" class="tnum">' +
        '<span style="background:var(--green);color:var(--ink);font-weight:900;padding:4px 10px;border-radius:8px">' + nis(p.min) + " ₪</span>" +
        '<span style="color:var(--muted-dark);font-weight:800">←</span>' +
        '<span style="color:var(--red);font-weight:900;text-decoration:line-through;text-decoration-thickness:2px">' + nis(p.max) + " ₪</span></div>" +
      "</button>";
  }).join("");

  var chips = h.quick.map(function (c) {
    return '<button class="chip" style="border-color:' + c.tint + '" data-open="' + esc(c.barcode) + '">' + esc(c.name) + "</button>";
  }).join("");

  return '<main>' +
    '<div class="hero" id="hero">' +
      '<div class="hero-layer" style="inset:-40px;transform:translate(' + px1 + "," + py1 + ')">' +
        '<div style="position:absolute;width:340px;height:340px;background:var(--green);left:-80px;top:-100px;animation:blob 9s ease-in-out infinite"></div>' +
        '<div style="position:absolute;width:240px;height:240px;background:var(--red);right:-40px;bottom:-80px;animation:blob 7s ease-in-out infinite reverse"></div></div>' +
      '<div class="hero-layer" style="inset:0;transform:translate(' + px2 + "," + py2 + ')">' +
        '<div style="position:absolute;width:120px;height:120px;border-radius:30px;background:var(--yellow);right:12%;top:20px;animation:spin 24s linear infinite"></div>' +
        '<div style="position:absolute;width:70px;height:70px;border-radius:50%;background:var(--purple);left:14%;bottom:60px;animation:float 5s ease-in-out infinite"></div>' +
        '<div style="position:absolute;width:44px;height:44px;background:#fff;left:8%;top:30%;clip-path:polygon(50% 0,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%);animation:spin 12s linear infinite"></div></div>' +
      '<div style="position:absolute;right:6%;bottom:22%;font-size:120px;font-weight:900;color:rgba(255,255,255,.06);line-height:1;transform:rotate(-12deg);pointer-events:none">₪</div>' +
      '<div class="hero-inner">' +
        '<div class="live-badge"><span class="live-dot"></span>' + num(m.stores_today) + " סניפים עודכנו ב־" + dateHe(m.latest_date) + "</div>" +
        "<h1>איפה <span class=\"rot\"><span><span style='display:block'>החלב</span><span style='display:block'>הביצים</span><span style='display:block'>הקפה</span><span style='display:block'>השמן</span><span style='display:block'>החלב</span></span></span><br>הכי זול היום?</h1>" +
        '<p style="margin:0;color:var(--light-dark);font-size:18px;text-align:center;max-width:560px">חפשו מוצר ותראו את המחיר בכל סניף בארץ, לפי הקבצים שהרשתות מחויבות לפרסם.</p>' +
        '<div style="position:relative;width:100%">' +
          '<div class="searchbox' + (S.focused ? " on" : "") + '">' +
            '<span style="font-size:24px;font-weight:900">⌕</span>' +
            '<input id="q" value="' + esc(S.query) + '" placeholder="חפשו מוצר, ברקוד או מותג…" autocomplete="off">' +
            '<button class="btn btn-green" style="border:0;padding:12px 22px" data-search>חיפוש</button>' +
          "</div>" + sug +
        "</div>" +
        '<button class="scan-cta" data-go="scan">' +
          '<span style="width:44px;height:44px;border-radius:12px;background:var(--ink);color:var(--yellow);display:grid;place-items:center;font-size:22px;flex:none">▦</span>' +
          '<span style="display:flex;flex-direction:column;gap:2px"><span style="font-size:16px;font-weight:900">יש לכם קבלה מהסופר? הדביקו אותה</span><span style="font-size:13px;font-weight:600">נראה לכם כמה הייתם חוסכים על אותו סל בדיוק</span></span>' +
          '<span style="font-size:22px;font-weight:900;margin-inline-start:6px">←</span></button>' +
        '<div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:center">' + chips + "</div>" +
      "</div></div>" +
    deal +
    '<section class="wrap" style="display:flex;flex-direction:column;gap:18px">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">' +
        '<h2 class="tag-yellow">🔥 הפערים הגדולים היום</h2>' +
        '<div class="small" style="color:#fff;background:var(--ink);padding:6px 12px;border-radius:999px;font-weight:600">הפער = ההפרש בין הסניף הזול ליקר</div>' +
      "</div>" +
      '<div class="pgrid">' + pop + "</div>" +
      '<div class="note">' + esc(freshnessNote()) + "</div>" +
    "</section></main>";
}

// ------------------------------------------------------------------ product
function screenProduct() {
  var d = S.product;
  if (!d) return '<div class="loading"><span class="spinner"></span> טוען מוצר…</div>';
  if (d.error) return '<div class="wrap"><div class="card">' + esc(d.error) + "</div></div>";
  var p = d.product, st = d.stats;

  var cityOpts = ['<option value="">כל הארץ</option>'].concat(S.cities.map(function (c) {
    return '<option value="' + esc(c.name) + '"' + (S.city === c.name ? " selected" : "") + ">" + esc(c.name) + " (" + c.stores + ")</option>";
  })).join("");

  var chainRows = d.all_chains.map(function (c, i) {
    var on = !S.chains || S.chains.indexOf(c) >= 0;
    return '<label class="chk-row" data-chain="' + esc(c) + '" style="background:' + (on ? "transparent" : "var(--bg)") + '">' +
      '<span class="chk" style="background:' + (on ? "var(--green)" : "#fff") + '">' + (on ? "✓" : "") + "</span>" +
      '<span style="flex:1">' + esc(c) + "</span>" +
      '<span class="dot" style="background:' + heat(i, d.all_chains.length) + '"></span></label>';
  }).join("");

  if (!st) {
    return '<div class="prod-wrap"><div class="prod-main"><div class="card">' +
      "<h1>" + esc(p.name) + "</h1><p>אין מחירים שתואמים את הסינון" +
      (S.city ? " בעיר " + esc(S.city) : "") + ".</p>" +
      '<button class="btn" data-clear-filters>נקה סינון</button></div></div></div>';
  }

  // KPI
  var kpis = '<div class="grid-auto">' +
    '<div class="kpi" style="background:var(--green)"><div style="font-size:13px;font-weight:800">הכי זול' + (S.city ? " ב" + esc(S.city) : " בארץ") + ' 🏆</div>' +
      '<div class="kpi-val tnum"><span data-count="' + st.min + '" data-key="pmin">' + nis(st.min) + '</span><span style="font-size:18px;font-weight:700"> ₪</span></div>' +
      '<div class="small" style="color:var(--green-dark);font-weight:600;line-height:1.4">' + esc(st.min_branch.chain) + " · " + esc(st.min_branch.branch) + ", " + esc(st.min_branch.city) +
        (st.min_ties > 1 ? " ועוד " + (st.min_ties - 1) + " סניפים באותו מחיר" : "") +
        "<br>עודכן " + dateHe(st.min_branch.date) + "</div></div>" +
    '<div class="kpi" style="background:var(--red);animation-delay:.08s"><div style="font-size:13px;font-weight:800;color:#fff">הכי יקר' + (S.city ? "" : " בארץ") + ' 💸</div>' +
      '<div class="kpi-val tnum" style="color:#fff"><span data-count="' + st.max + '" data-key="pmax">' + nis(st.max) + '</span><span style="font-size:18px;font-weight:700"> ₪</span></div>' +
      '<div class="small" style="color:var(--red-tint);font-weight:600;line-height:1.4">' + esc(st.max_branch.chain) + " · " + esc(st.max_branch.branch) + ", " + esc(st.max_branch.city) +
        (st.max_ties > 1 ? " ועוד " + (st.max_ties - 1) + " סניפים באותו מחיר" : "") +
        "<br>עודכן " + dateHe(st.max_branch.date) + "</div></div>" +
    '<div class="kpi" style="background:#fff;animation-delay:.16s"><div style="font-size:13px;font-weight:800;color:var(--muted)">חציון</div>' +
      '<div class="kpi-val tnum">' + nis(st.median) + '<span style="font-size:18px;font-weight:700"> ₪</span></div>' +
      '<div class="small muted">מתוך ' + num(st.count) + " סניפים</div></div>" +
    '<div class="kpi" style="background:var(--yellow);animation-delay:.24s"><div style="font-size:13px;font-weight:800">פער בין הזול ליקר</div>' +
      '<div class="kpi-val tnum">' + pctStr(st.gap_pct) + "</div>" +
      '<div class="small" style="color:var(--yellow-dark);font-weight:600">' + nis(st.gap_shekel) + " ₪ על יחידה אחת</div></div>" +
  "</div>";

  // bars
  var BAR_MAX = 12;
  var barRows = d.chain_rows.slice(0, BAR_MAX);
  var maxAvg = Math.max.apply(null, barRows.map(function (c) { return c.avg; })) || 1;
  var bars = barRows.map(function (c, i) {
    var hh = Math.max(6, Math.round(c.avg / maxAvg * 165));
    return '<div class="bar-col" title="' + esc(c.chain) + ": ממוצע " + nis(c.avg) + " ₪ מתוך " + c.stores + ' סניפים">' +
      '<div style="font-size:14px;font-weight:900" class="tnum">' + nis(c.avg) + "</div>" +
      '<div class="bar" style="height:' + hh + "px;background:" + c.color + ";animation-delay:" + (i * 70) + 'ms"></div>' +
      '<div style="font-size:11px;text-align:center;line-height:1.2;height:34px;font-weight:700;overflow:hidden">' + esc(c.chain) + "</div></div>";
  }).join("");

  // map
  var mapPins = "", noGeo = 0;
  d.city_rows.forEach(function (c, i) {
    var g = S.geo[c.city];
    if (!g) { noGeo++; return; }
    var xy = latlngToXY(g[0], g[1]);
    var size = 10 + Math.min(10, Math.round(c.stores / 6));
    mapPins += '<div class="map-pin" style="left:' + xy.x + "px;top:" + xy.y + "px;width:" + size + "px;height:" + size + "px;background:" + c.color +
      ";animation-delay:" + (i * 40) + 'ms" title="' + esc(c.city) + ": מ־" + nis(c.min) + " ₪ · " + c.stores + ' סניפים"></div>';
  });
  var legend = d.city_rows.slice(0, 6).map(function (c) {
    return '<div style="display:flex;align-items:center;gap:8px;font-size:14px"><span class="dot" style="background:' + c.color + '"></span>' +
      '<span style="flex:1;font-weight:600">' + esc(c.city) + '</span><span style="font-weight:900" class="tnum">' + nis(c.min) + "</span></div>";
  }).join("");

  // history
  var hist = "";
  if (d.history.length > 1) {
    var hs = d.history, W = 600, H = 220;
    var vals = hs.map(function (r) { return r.median; });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var pad = (hi - lo) * 0.15 || 1; lo -= pad; hi += pad;
    var X = function (i) { return 40 + i / (hs.length - 1) * 550; };
    var Y = function (v) { return 20 + (1 - (v - lo) / (hi - lo)) * 150; };
    var pts = hs.map(function (r, i) { return X(i).toFixed(1) + "," + Y(r.median).toFixed(1); }).join(" ");
    var labels = "";
    var hIdx = [0, Math.floor(hs.length / 2), hs.length - 1];
    hIdx.forEach(function (i, k) {
      var shift = k === 0 ? "0" : (k === hIdx.length - 1 ? "-100%" : "-50%");
      labels += '<div style="position:absolute;left:' + (X(i) / W * 100) + '%;top:86%;transform:translateX(' + shift + ');font-size:11px;font-weight:700;white-space:nowrap">' + dateHe(hs[i].date) + "</div>";
    });
    hist = '<section class="card" style="display:flex;flex-direction:column;gap:14px">' +
      '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px"><h3 class="h3">היסטוריית מחיר (חציון ארצי)</h3><span class="small muted">' + hs.length + " ימים</span></div>" +
      '<div style="position:relative;direction:ltr">' +
      '<svg viewBox="0 0 ' + W + " " + H + '" style="width:100%;height:auto;display:block">' +
        '<line x1="40" y1="20" x2="590" y2="20" stroke="var(--div2)" stroke-dasharray="4 4"/>' +
        '<line x1="40" y1="95" x2="590" y2="95" stroke="var(--div2)" stroke-dasharray="4 4"/>' +
        '<line x1="40" y1="170" x2="590" y2="170" stroke="var(--ink)" stroke-width="2"/>' +
        '<polyline points="' + pts + '" fill="none" stroke="var(--purple)" style="stroke-width:4;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:2400;animation:draw 1.6s ease-out both"/>' +
      "</svg>" +
      '<div style="position:absolute;right:calc(100% - 6%);top:4%;font-size:11px;font-weight:700" class="muted tnum">' + nis(hi) + "</div>" +
      '<div style="position:absolute;right:calc(100% - 6%);top:74%;font-size:11px;font-weight:700" class="muted tnum">' + nis(lo) + "</div>" +
      labels + "</div>" +
      '<div class="note">החציון מחושב מכל הסניפים שדיווחו על המוצר באותו יום. ימים שבהם הרשתות לא פרסמו קובץ אינם מופיעים.</div>' +
      "</section>";
  } else {
    // אין גרף כשהמוצר לא נמצא במעקב, ולא בגלל שההיסטוריה "עוד תיצבר"
    hist = '<section class="card"><h3 class="h3">היסטוריית מחיר</h3>' +
      '<p class="note" style="margin-top:10px">' +
      (d.history.length === 1
        ? 'יש רק יום אחד של נתונים למוצר הזה, וזה לא מספיק לגרף.'
        : 'המוצר הזה אינו במעקב היסטורי. מעקב נשמר למוצרים הנמכרים בהכי הרבה סניפים, ' +
          'והמחירים שלמעלה מעודכנים לכל המוצרים.') +
      "</p></section>";
  }

  // top 10 table
  var rows = d.branches.slice(0, 10).map(function (b, i) {
    var vs = pctStr(((b.price - st.median) / st.median) * 100);
    var col = b.price <= st.median ? "var(--green)" : "var(--red)";
    return '<tr' + (i === 0 ? ' style="background:var(--green-tint)"' : "") + ">" +
      "<td>" + (i + 1) + "</td><td>" + esc(b.chain) + "</td>" +
      "<td>" + esc(b.branch) + (b.note ? ' <span class="small muted" title="' + esc(b.note) + '">ⓘ</span>' : "") + "</td>" +
      '<td class="col-opt">' + esc(b.city) + "</td>" +
      '<td class="tnum" style="font-weight:900">' + nis(b.price) + "</td>" +
      '<td class="tnum small col-opt">' + dateHe(b.date) + "</td>" +
      '<td><span style="background:' + col + ';color:#fff;border-radius:6px;padding:2px 7px;font-weight:800;font-size:12px">' + vs + "</span></td></tr>";
  }).join("");

  var inCart = S.cart.some(function (c) { return c.barcode === p.barcode; });
  var warnings = [];
  if (d.excluded_old) warnings.push("הושמטו " + num(d.excluded_old) + " מחירים ישנים מ־" + S.meta.fresh_days + " ימים (סניפים שהרשת הפסיקה לפרסם).");
  if (d.no_city_count) warnings.push(num(d.no_city_count) + " סניפים ללא עיר בקובץ הרשת מסומנים כ\"לא ידוע\".");
  if (noGeo) warnings.push(noGeo + " ערים אינן מוצגות על המפה (אין להן קואורדינטות ברשימה).");

  return '<div class="prod-wrap">' +
    '<aside class="side">' +
      '<button class="filter-head" data-filter-toggle><span class="h3">סינון</span>' +
        '<span class="small muted">' + (S.city || "כל הארץ") + (S.chains ? " · " + S.chains.length + " רשתות" : "") + "</span>" +
        '<span class="filter-arrow">' + (S.filterOpen ? "▲" : "▼") + "</span></button>" +
      '<div class="filter-body' + (S.filterOpen ? "" : " hide") + '">' +
      '<div style="display:flex;flex-direction:column;gap:8px"><label class="small muted" style="font-weight:700">עיר</label>' +
        '<select id="citysel">' + cityOpts + "</select></div>" +
      '<div style="display:flex;flex-direction:column;gap:6px">' +
        '<div style="display:flex;justify-content:space-between;align-items:baseline"><label class="small muted" style="font-weight:700">רשתות</label>' +
        '<button style="border:0;background:none;color:var(--green-link);font-size:12px;font-weight:700;padding:0" data-allchains>בחר הכל</button></div>' +
        '<div style="max-height:260px;overflow-y:auto;overscroll-behavior:contain">' + chainRows + "</div></div>" +
      '<label class="chk-row" data-toggle-old style="padding:0"><span class="chk" style="background:' + (S.includeOld ? "var(--green)" : "#fff") + '">' + (S.includeOld ? "✓" : "") + '</span><span class="small" style="flex:1">כלול מחירים ישנים מ־' + S.meta.fresh_days + " ימים</span></label>" +
      '<div style="border-top:2px dashed var(--div2);padding-top:14px" class="note">' + num(d.branch_count) + " סניפים תואמים · הנתונים מ־" + dateHe(S.meta.latest_date) + "</div>" +
    "</div></aside>" +
    '<div class="prod-main">' +
      '<div class="small muted"><a data-go="home">חיפוש</a> ‹ <span style="color:var(--ink)">' + esc(p.name) + "</span></div>" +
      '<div class="prod-head" style="background:' + p.tint + '">' +
        '<div style="width:130px;height:130px;border-radius:18px;flex:none;background:#fff;border:3px solid var(--ink);display:grid;place-items:center;color:var(--muted);font-size:11px;font-weight:700;animation:float 4s ease-in-out infinite;text-align:center;padding:8px">אין תמונה<br>בקבצי הרשתות</div>' +
        '<div style="flex:1 1 260px;display:flex;flex-direction:column;gap:8px;min-width:0;position:relative">' +
          '<div style="font-size:13px;font-weight:800;background:var(--ink);color:#fff;width:fit-content;padding:3px 10px;border-radius:999px">' + num(p.stores) + " סניפים · " + num(p.chains) + " רשתות</div>" +
          '<h1 style="font-size:34px;font-weight:900;line-height:1.1">' + esc(p.name) + "</h1>" +
          '<div style="display:flex;align-items:center;gap:10px" class="mono small">' +
            '<span style="display:inline-block;width:64px;height:20px;background:repeating-linear-gradient(90deg,var(--ink) 0 2px,transparent 2px 4px,var(--ink) 4px 5px,transparent 5px 8px)"></span>' +
            "<span>" + esc(p.barcode) + "</span></div></div>" +
        '<div style="display:flex;gap:10px;flex-wrap:wrap;position:relative">' +
          '<div style="position:relative"><button class="btn" style="background:' + (inCart ? "var(--green)" : "var(--ink)") + ";color:" + (inCart ? "var(--ink)" : "#fff") + ';box-shadow:4px 4px 0 #fff" data-add="' + esc(p.barcode) + '">' + (inCart ? "✓ בסל" : "+ הוסף לסל") + "</button>" +
            (S.burst ? confettiHtml() : "") + "</div></div></div>" +
      kpis +
      (warnings.length ? '<div class="warn">' + warnings.map(esc).join("<br>") + "</div>" : "") +
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px">' +
        '<section class="card" style="display:flex;flex-direction:column;gap:16px"><div style="display:flex;justify-content:space-between;align-items:baseline"><h3 class="h3">מחיר ממוצע לפי רשת</h3><span class="small muted">מהזול ← ליקר</span></div>' +
          '<div class="bars">' + bars + "</div>" +
          (d.chain_rows.length > BAR_MAX ? '<div class="note">מוצגות ' + BAR_MAX + " הרשתות הזולות מתוך " + d.chain_rows.length + " שמוכרות את המוצר.</div>" : "") +
          "</section>" +
        '<section class="card" style="display:flex;flex-direction:column;gap:14px"><div style="display:flex;justify-content:space-between;align-items:baseline"><h3 class="h3">ערים על המפה</h3><span class="small muted">צבע = מחיר</span></div>' +
          '<div style="display:flex;gap:16px;align-items:stretch;flex-wrap:wrap">' + mapSvg(mapPins, d.city_rows.length) +
          '<div style="flex:1;min-width:150px;display:flex;flex-direction:column;gap:10px;justify-content:center">' +
            '<div class="small muted" style="font-weight:700">סקאלת מחיר</div>' +
            '<div style="height:14px;border-radius:7px;border:2px solid var(--ink);background:linear-gradient(90deg,var(--red),var(--yellow),var(--green))"></div>' +
            '<div style="display:flex;justify-content:space-between;font-weight:900" class="tnum small"><span style="color:var(--green-link)">' + nis(st.min) + " ₪</span><span style=\"color:var(--red)\">" + nis(st.max) + " ₪</span></div>" +
            '<div style="display:flex;flex-direction:column;gap:6px;margin-top:8px">' + legend + "</div></div></div>" +
          '<div class="note">מיקום מקורב לפי מרכז היישוב, לא לפי כתובת הסניף.</div></section>' +
        hist +
        '<section class="card" style="display:flex;flex-direction:column;gap:14px;min-width:0"><div style="display:flex;justify-content:space-between;align-items:baseline"><h3 class="h3">10 הסניפים הזולים</h3><span class="small" style="color:#fff;background:var(--purple);padding:3px 10px;border-radius:999px;font-weight:700">' + esc(S.city || "כל הארץ") + "</span></div>" +
          '<div style="overflow-x:auto"><table class="tbl-opt"><thead><tr><th>#</th><th>רשת</th><th>סניף</th><th class="col-opt">עיר</th><th>מחיר</th><th class="col-opt">תאריך</th><th>מול חציון</th></tr></thead><tbody>' + rows + "</tbody></table></div>" +
          '<div class="note">' + esc(freshnessNote()) + "</div></section>" +
      "</div></div></div>";
}

function confettiHtml() {
  var out = '<div style="position:absolute;left:50%;top:50%;pointer-events:none">';
  for (var i = 0; i < 14; i++) {
    var a = i / 14 * Math.PI * 2, r = 40 + Math.random() * 50;
    out += '<div style="position:absolute;width:10px;height:10px;border-radius:' + (i % 2 ? "50%" : "2px") +
      ";background:" + HEAT[i % HEAT.length] + ";--dx:" + (Math.cos(a) * r).toFixed(0) + "px;--dy:" + (Math.sin(a) * r).toFixed(0) +
      'px;animation:confetti .9s cubic-bezier(.2,.8,.3,1) both"></div>';
  }
  return out + "</div>";
}

// מיפוי קואורדינטות לקנבס המפה המסוגננת (200x300)
function latlngToXY(lat, lng) {
  var y = 6 + (33.33 - lat) * 74.7;
  y = Math.max(8, Math.min(292, y));
  var b = mapBounds(y);
  var x = b.w + (lng - 34.25) / (35.95 - 34.25) * 96;
  x = Math.max(b.w + 5, Math.min(b.e - 5, x));
  return { x: Math.round(x), y: Math.round(y) };
}
// גבולות המתאר המסוגנן לפי גובה, כדי שהנקודות יישבו בתוך היבשה
var MAP_W = [[6,84],[24,76],[44,70],[62,66],[82,64],[100,62],[118,58],[136,52],[154,48],[174,50],[194,56],[214,64],[236,74],[256,80],[274,84],[294,92]];
var MAP_E = [[6,112],[24,130],[34,134],[52,128],[70,120],[88,112],[104,108],[116,100],[128,86],[140,76],[154,72],[168,78],[178,92],[186,106],[200,112],[216,108],[232,102],[250,98],[268,96],[284,98]];
function interp(tbl, y) {
  if (y <= tbl[0][0]) return tbl[0][1];
  for (var i = 1; i < tbl.length; i++) {
    if (y <= tbl[i][0]) {
      var a = tbl[i - 1], b = tbl[i];
      return a[1] + (b[1] - a[1]) * (y - a[0]) / (b[0] - a[0]);
    }
  }
  return tbl[tbl.length - 1][1];
}
function mapBounds(y) { return { w: interp(MAP_W, y), e: interp(MAP_E, y) }; }

function mapSvg(pins, cityCount) {
  return '<div class="map-box">' +
    '<svg viewBox="0 0 200 300" style="position:absolute;inset:0;width:100%;height:100%;direction:ltr">' +
    '<defs><pattern id="sea" width="10" height="10" patternUnits="userSpaceOnUse"><path d="M0 5 Q2.5 2 5 5 T10 5" fill="none" stroke="rgba(20,21,26,.12)" stroke-width="1"/></pattern></defs>' +
    '<rect width="200" height="300" fill="url(#sea)"/>' +
    '<path d="M86 6 L112 4 L128 12 L134 34 L128 52 L120 70 L112 88 L108 104 L100 116 L86 128 L76 140 L72 154 L78 168 L92 178 L106 186 L112 200 L108 216 L102 232 L98 250 L96 268 L98 284 L94 294 L88 290 L84 274 L80 256 L74 236 L64 214 L56 194 L50 174 L48 154 L52 136 L58 118 L62 100 L64 82 L66 62 L70 44 L76 24 Z" fill="var(--bg)" stroke="var(--ink)" stroke-width="3" stroke-linejoin="round"/>' +
    '<path d="M124 60 L134 60 L136 72 L128 78 Z" fill="#7cc7ff" stroke="var(--ink)" stroke-width="2"/>' +
    '<path d="M104 118 L114 116 L118 136 L112 150 L104 148 Z" fill="#7cc7ff" stroke="var(--ink)" stroke-width="2"/>' +
    '<text x="24" y="150" font-size="9" font-weight="800" fill="rgba(20,21,26,.45)" transform="rotate(-72 24 150)">הים התיכון</text></svg>' +
    pins +
    '<div style="position:absolute;right:8px;top:8px;background:var(--ink);color:#fff;font-size:10px;font-weight:800;padding:2px 8px;border-radius:999px">' + cityCount + " ערים</div></div>";
}

// ------------------------------------------------------------------ market
function screenMarket() {
  var d = S.market;
  if (!d) return '<div class="mkt"><div class="loading"><span class="spinner"></span> טוען…</div></div>';
  var sel = d.selected;
  if (!sel) return '<div class="mkt"><div class="loading">אין נתוני מגמה עדיין.</div></div>';

  var up = d.items.filter(function (i) { return i.change > 0; }).length;
  var down = d.items.filter(function (i) { return i.change < 0; }).length;

  var list = d.items.map(function (i) {
    var col = i.change == null || i.change === 0 ? "var(--muted)"
              : (i.change < 0 ? "var(--green)" : "var(--red)");
    var sp = "";
    if (i.spark && i.spark.length > 1) {
      var mn = Math.min.apply(null, i.spark), mx = Math.max.apply(null, i.spark), rg = (mx - mn) || 1;
      sp = '<svg viewBox="0 0 56 20" preserveAspectRatio="none" style="width:56px;height:20px;direction:ltr"><polyline points="' +
        i.spark.map(function (v, k) { return (k / (i.spark.length - 1) * 56).toFixed(1) + "," + (18 - (v - mn) / rg * 16).toFixed(1); }).join(" ") +
        '" fill="none" stroke="' + col + '" stroke-width="1.5"/></svg>';
    }
    return '<div class="mkt-row' + (i.barcode === sel.barcode ? " on" : "") + '" data-mkt="' + esc(i.barcode) + '">' +
      '<div style="min-width:0"><div class="mono" style="font-size:11px;color:var(--yellow)">' + esc(i.symbol) + "</div>" +
      '<div style="font-size:12px;color:var(--light-dark);font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(i.name) + "</div></div>" +
      "<div>" + sp + "</div>" +
      '<div class="mono" style="font-size:14px;font-weight:800">' + nis(i.price) + "</div>" +
      '<div class="mono" style="font-size:11px;font-weight:800;color:' + col + '">' + (i.change == null ? "—" : pctStr(i.change)) + "</div></div>";
  }).join("");

  // chart
  var series = sel.series || [];
  var cutoff = { "1W": 7, "1M": 30, "6M": 182, "1Y": 365, "ALL": 99999 }[S.range] || 30;
  var view = series.slice(Math.max(0, series.length - cutoff));
  var chart = '<div class="mkt-card" style="padding:18px"><div class="loading" style="padding:30px">אין מספיק היסטוריה לטווח הזה</div></div>';
  if (view.length > 1) {
    var W = 800, H = 300;
    var vals = view.map(function (r) { return r.median; });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var pad = (hi - lo) * .18 || .5; lo -= pad; hi += pad;
    var X = function (i) { return 18 + i / (view.length - 1) * (W - 90); };
    var Y = function (v) { return 18 + (1 - (v - lo) / (hi - lo)) * (H - 46); };
    var line = view.map(function (r, i) { return (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(r.median).toFixed(1); }).join(" ");
    var area = line + " L" + X(view.length - 1).toFixed(1) + " " + (H - 12) + " L" + X(0).toFixed(1) + " " + (H - 12) + " Z";
    var col = sel.change == null ? "var(--yellow)" : (sel.change < 0 ? "var(--green)" : "var(--red)");
    var med = sel.today ? sel.today.median : null;
    var medY = med != null && med >= lo && med <= hi ? Y(med) : null;
    var grid = "", xl = "";
    [0, .25, .5, .75, 1].forEach(function (f) {
      var v = hi - (hi - lo) * f;
      grid += '<div style="position:absolute;left:93.5%;top:' + (Y(v) / H * 100) + '%;transform:translateY(-50%);font-size:11px;color:var(--muted);font-weight:700;white-space:nowrap" class="tnum">' + nis(v) + "</div>";
    });
    var xIdx = [0, Math.floor(view.length / 2), view.length - 1];
    xIdx.forEach(function (i, k) {
      var shift = k === 0 ? "0" : (k === xIdx.length - 1 ? "-100%" : "-50%");
      xl += '<div style="position:absolute;left:' + (X(i) / W * 100) + '%;top:97%;transform:translate(' + shift + ',-100%);font-size:11px;color:var(--muted);font-weight:700;white-space:nowrap">' + dateHe(view[i].date) + "</div>";
    });
    chart = '<div class="mkt-card" style="position:relative;padding:18px">' +
      '<svg viewBox="0 0 ' + W + " " + H + '" style="width:100%;height:auto;display:block;direction:ltr">' +
      '<defs><linearGradient id="af" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="' + col + '" stop-opacity=".35"/><stop offset="100%" stop-color="' + col + '" stop-opacity="0"/></linearGradient></defs>' +
      '<line x1="0" y1="' + (H / 4) + '" x2="' + (W - 60) + '" y2="' + (H / 4) + '" stroke="#2b2d36" stroke-dasharray="3 6"/>' +
      '<line x1="0" y1="' + (H / 2) + '" x2="' + (W - 60) + '" y2="' + (H / 2) + '" stroke="#2b2d36" stroke-dasharray="3 6"/>' +
      '<line x1="0" y1="' + (3 * H / 4) + '" x2="' + (W - 60) + '" y2="' + (3 * H / 4) + '" stroke="#2b2d36" stroke-dasharray="3 6"/>' +
      (medY ? '<line x1="0" y1="' + medY.toFixed(1) + '" x2="' + (W - 60) + '" y2="' + medY.toFixed(1) + '" stroke="var(--yellow)" stroke-width="1.5" stroke-dasharray="2 6"/>' : "") +
      '<path d="' + area + '" fill="url(#af)"/>' +
      '<path d="' + line + '" fill="none" stroke="' + col + '" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" style="stroke-dasharray:2400;animation:draw 1.4s ease-out both"/>' +
      '<circle cx="' + X(view.length - 1).toFixed(1) + '" cy="' + Y(view[view.length - 1].median).toFixed(1) + '" r="7" fill="' + col + '" stroke="var(--ink)" stroke-width="3"/>' +
      "</svg>" +
      '<div style="position:absolute;left:18px;right:18px;top:18px;bottom:10px;pointer-events:none">' + grid + xl + "</div></div>";
  }

  var depth = (sel.depth || []).map(function (dd, i) {
    var mx = Math.max.apply(null, sel.depth.map(function (x) { return x.avg; })) || 1;
    return '<div style="display:grid;grid-template-columns:110px 1fr auto;gap:4px 10px;align-items:center;font-size:13px">' +
      '<span style="font-weight:700;color:var(--light-dark);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(dd.chain) + "</span>" +
      '<div style="height:18px;position:relative;direction:ltr"><div style="position:absolute;right:0;top:0;bottom:0;width:' + (dd.avg / mx * 100).toFixed(0) + "%;background:" + dd.color + ';opacity:.35;border-radius:3px"></div></div>' +
      '<span class="mono" style="font-weight:800;color:' + dd.color + '">' + nis(dd.avg) + "</span></div>";
  }).join("");

  function moverRow(m, col) {
    return '<div style="display:flex;justify-content:space-between;gap:8px;font-size:12px;cursor:pointer;padding:3px 0" data-mkt="' + esc(m.barcode) + '">' +
      '<span style="color:var(--light-dark);font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><span class="mono" style="color:var(--yellow);font-size:10px">' + esc(m.symbol) + "</span> " + esc(m.name) + "</span>" +
      '<span class="mono" style="font-weight:800;color:' + col + '">' + pctStr(m.change) + "</span></div>";
  }

  var sig = sel.change == null ? { bg: "var(--yellow)", icon: "🟡", t: "אין נתון השוואה", x: "לא נמצא יום קודם עם נתונים למוצר הזה." }
    : sel.change <= -3 ? { bg: "var(--green)", icon: "🟢", t: "המחיר ירד", x: "החציון הארצי ירד ב־" + Math.abs(sel.change).toFixed(1) + "% מאז " + dateHe(sel.prev_date) + "." }
    : sel.change >= 3 ? { bg: "var(--red)", icon: "🔴", t: "המחיר בעלייה", x: "החציון הארצי עלה ב־" + sel.change.toFixed(1) + "% מאז " + dateHe(sel.prev_date) + "." }
    : { bg: "var(--yellow)", icon: "🟡", t: "מחיר יציב", x: "שינוי של " + pctStr(sel.change) + " מאז " + dateHe(sel.prev_date) + "." };

  var t = sel.today || {};
  var chgCol = sel.change == null || sel.change === 0 ? "var(--muted)"
               : (sel.change < 0 ? "var(--green)" : "var(--red)");

  return '<div class="mkt">' +
    '<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:18px">' +
      '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><h1 style="font-size:30px;font-weight:900">בורסת המחירים</h1>' +
      '<span class="pill" style="background:var(--card-dark);border:2px solid var(--border-dark);color:var(--light-dark);display:flex;align-items:center;gap:6px"><span style="width:8px;height:8px;border-radius:50%;background:var(--green);animation:blink 1.6s infinite"></span>עודכן ' + dateHe(d.meta.latest_date) + "</span></div>" +
      '<div style="display:flex;gap:14px;font-size:13px;font-weight:800;flex-wrap:wrap"><span style="color:var(--green)">ירדו ' + down + '</span><span style="color:var(--red)">עלו ' + up + '</span><span class="muted">' + d.items.length + " מוצרים במעקב</span></div>" +
    "</div>" +
    '<div style="display:grid;grid-template-columns:minmax(0,340px) minmax(0,1fr);gap:20px" class="mkt-grid">' +
      '<div class="mkt-card" style="padding:6px;max-height:78vh;overflow-y:auto">' + list + "</div>" +
      '<div style="display:flex;flex-direction:column;gap:12px;min-width:0">' +
        '<div class="mkt-card">' +
          '<div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px">' +
            "<div><div style=\"display:flex;align-items:center;gap:8px\"><span class='mono pill' style='background:var(--yellow);color:var(--ink);font-size:11px'>" + esc(sel.symbol) + "</span><span class='small muted'>חציון ארצי · " + num(sel.stores) + " סניפים</span></div>" +
            '<h2 style="font-size:30px;font-weight:900;margin-top:6px">' + esc(sel.name) + "</h2></div>" +
            '<div style="text-align:left"><div class="mono" style="font-size:52px;font-weight:800;line-height:1">' + nis(sel.price) + "</div>" +
            '<div class="mono" style="font-size:18px;font-weight:800;color:' + chgCol + '">' +
            (sel.change == null ? "אין השוואה"
             : sel.change === 0 ? "ללא שינוי"
             : (sel.change < 0 ? "▼ " : "▲ ") + pctStr(sel.change)) + "</div></div>" +
          "</div>" +
          '<div class="mono small muted" style="margin-top:10px">עדכון אחרון ' + dateHe(sel.date) + (sel.prev_date ? " · קודם " + dateHe(sel.prev_date) + " · " + nis(sel.prev) + " ₪" : "") + "</div>" +
          '<div style="display:flex;gap:6px;margin-top:12px;flex-wrap:wrap">' +
            ["1W", "1M", "6M", "1Y", "ALL"].map(function (r) {
              var lbl = { "1W": "שבוע", "1M": "חודש", "6M": "6 חודשים", "1Y": "שנה", "ALL": "הכל" }[r];
              return '<button class="rng-tab' + (S.range === r ? " on" : "") + '" data-range="' + r + '">' + lbl + "</button>";
            }).join("") + "</div></div>" +
        chart +
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px">' +
          '<div class="stat-tile"><div class="small muted" style="font-weight:800">הזול היום</div><div class="tnum" style="font-size:22px;font-weight:900;color:var(--green)">' + nis(t.min) + " ₪</div></div>" +
          '<div class="stat-tile"><div class="small muted" style="font-weight:800">היקר היום</div><div class="tnum" style="font-size:22px;font-weight:900;color:var(--red)">' + nis(t.max) + " ₪</div></div>" +
          '<div class="stat-tile"><div class="small muted" style="font-weight:800">פער היום</div><div class="tnum" style="font-size:22px;font-weight:900">' + pctStr(t.gap_pct) + "</div></div>" +
          '<div class="stat-tile"><div class="small muted" style="font-weight:800">סניפים מדווחים</div><div class="tnum" style="font-size:22px;font-weight:900">' + num(sel.stores) + "</div></div>" +
          '<div class="stat-tile"><div class="small muted" style="font-weight:800">ימים במעקב</div><div class="tnum" style="font-size:22px;font-weight:900">' + series.length + "</div></div>" +
        "</div>" +
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">' +
          '<section class="mkt-card" style="display:flex;flex-direction:column;gap:8px"><div style="display:flex;justify-content:space-between;align-items:baseline"><div style="font-size:13px;font-weight:900">עומק שוק · מחיר ממוצע לפי רשת</div></div>' + depth + "</section>" +
          '<section class="mkt-card" style="display:flex;flex-direction:column;gap:6px"><div style="font-size:13px;font-weight:900">המובילים מאז העדכון הקודם</div>' +
            '<div class="small" style="font-weight:800;color:var(--green)">🟢 ירדו הכי הרבה (טוב לקנות)</div>' + d.losers.map(function (m) { return moverRow(m, "var(--green)"); }).join("") +
            '<div class="small" style="font-weight:800;color:var(--red);margin-top:4px">🔴 עלו הכי הרבה</div>' + d.gainers.map(function (m) { return moverRow(m, "var(--red)"); }).join("") +
          "</section></div>" +
        '<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;background:' + sig.bg + ';border:3px solid var(--ink);border-radius:16px;padding:14px 18px;color:var(--ink)">' +
          '<span style="font-size:22px">' + sig.icon + "</span>" +
          '<div style="flex:1;min-width:200px"><div style="font-size:15px;font-weight:900">' + sig.t + '</div><div style="font-size:13px;font-weight:600">' + esc(sig.x) + "</div></div>" +
          '<button class="btn btn-ink" style="padding:10px 16px;font-size:14px" data-open="' + esc(sel.barcode) + '">איפה הכי זול עכשיו ←</button></div>' +
        '<div class="note" style="color:var(--muted)">הבורסה עוקבת אחרי ' + d.items.length + " המוצרים הנפוצים ביותר. השינוי מחושב מול היום הקודם שבו הרשתות פרסמו נתונים, ולא מול אתמול בהכרח.</div>" +
      "</div></div></div>";
}

// ------------------------------------------------------------------ scan
function screenScan() {
  if (S.scanPhase === "done" && S.scanResult) return scanResults();
  var busy = S.scanPhase === "scanning";
  return '<div class="wrap" style="display:flex;flex-wrap:wrap;gap:24px;align-items:flex-start">' +
    '<div style="flex:1 1 320px;display:flex;flex-direction:column;gap:16px">' +
      '<div class="pill" style="background:var(--yellow);border:3px solid var(--ink);width:fit-content;transform:rotate(-2deg);font-weight:900">▦ בדיקת קבלה</div>' +
      '<h1 style="font-size:38px;font-weight:900;line-height:1.1">כמה שילמתם <span style="color:var(--red)">יותר מדי</span> בקנייה האחרונה?</h1>' +
      '<p class="muted" style="font-size:16px;line-height:1.6">הדביקו את שורות הקבלה, ונשווה כל פריט מול המחיר שלו בכל סניף בארץ.</p>' +
      '<div style="display:flex;flex-direction:column;gap:10px">' +
        stepPill(1, "מדביקים את שורות הקבלה") + stepPill(2, "מזהים את המוצרים לפי שם או ברקוד") + stepPill(3, "מחשבים כמה אותו סל עולה בסניף הזול") +
      "</div>" +
      '<div class="warn">סריקת צילום של קבלה אינה נתמכת. הדביקו טקסט: קבלה דיגיטלית מהמייל או מאפליקציית הרשת, שורה לכל מוצר.</div>' +
    "</div>" +
    '<div style="flex:1 1 380px;display:flex;flex-direction:column;gap:12px">' +
      '<div class="drop" style="min-height:auto;align-items:stretch;text-align:right">' +
        '<div style="display:flex;align-items:center;gap:12px"><span style="width:44px;height:44px;border-radius:12px;background:var(--ink);color:var(--yellow);display:grid;place-items:center;font-size:22px;transform:rotate(-6deg);box-shadow:4px 4px 0 var(--yellow);flex:none">▦</span>' +
        '<div style="font-size:16px;font-weight:900">הדביקו כאן את שורות הקבלה</div></div>' +
        '<textarea id="scantext" rows="10" placeholder="לדוגמה:&#10;2 x חלב תנובה 3% 1 ליטר   14.40&#10;קוטג\' תנובה 5%   6.90&#10;7290004131074   7.20" style="width:100%;border:2px solid var(--ink);border-radius:12px;padding:12px;font-size:14px;font-family:\'JetBrains Mono\',monospace;line-height:1.8;resize:vertical">' + esc(S.scanText) + "</textarea>" +
        '<div style="display:flex;gap:10px;flex-wrap:wrap">' +
          '<button class="btn btn-green" data-scan-run ' + (busy ? "disabled" : "") + ">" + (busy ? '<span class="spinner"></span> בודקים…' : "בדקו את הקבלה") + "</button>" +
          '<button class="btn" data-scan-sample>מלא דוגמה</button>' +
          '<label class="btn" style="display:inline-flex;align-items:center">טען קובץ טקסט<input type="file" id="scanfile" accept=".txt,.csv,text/plain" style="display:none"></label>' +
        "</div>" +
        '<div class="note">אפשר גם לכתוב ברקודים בלבד, אחד בכל שורה. מחיר ששולם בסוף השורה הוא לא חובה, אבל בלעדיו לא נוכל להראות כמה שילמתם יותר מדי.</div>' +
      "</div></div></div>";
}
function stepPill(n, txt) {
  return '<div style="display:flex;align-items:center;gap:10px;background:#fff;border:3px solid var(--ink);border-radius:14px;padding:10px 14px;font-weight:700">' +
    '<span style="width:26px;height:26px;border-radius:50%;background:var(--ink);color:#fff;display:grid;place-items:center;font-size:13px;font-weight:900;flex:none">' + n + "</span>" + esc(txt) + "</div>";
}

function scanResults() {
  var r = S.scanResult, a = r.analysis;
  if (!a || !a.best) {
    return '<div class="wrap"><div class="card"><h1 style="font-size:26px">לא הצלחנו להשוות</h1>' +
      '<p class="muted" style="margin-top:10px">לא זוהו מוצרים מהקבלה. נסו לכתוב שם מוצר מלא יותר, או ברקוד.</p>' +
      (r.unmatched.length ? '<div class="note" style="margin-top:10px">שורות שלא זוהו: ' + esc(r.unmatched.map(function (u) { return u.desc; }).join(" · ")) + "</div>" : "") +
      '<button class="btn btn-ink" style="margin-top:16px" data-scan-reset>נסו קבלה אחרת</button></div></div>';
  }
  var paid = r.paid_total;
  var best = a.best;
  var bestTotal = best.total;
  var saving = paid != null ? paid - bestTotal : null;

  var rows = r.matched.map(function (m, i) {
    var code = m.product.barcode;
    var cheapest = a.cheapest_by_item ? a.cheapest_by_item[code] : null;
    var atBest = a.best_store_prices ? a.best_store_prices[code] : null;
    var paidLine = m.paid != null ? nis(m.paid) + " ₪" : '<span class="muted small">לא צוין</span>';
    var gap = (m.paid != null && cheapest) ? m.paid - cheapest.price : null;
    var gapCol = gap == null ? "var(--muted)" : gap > 0.01 ? "var(--green)" : "var(--muted)";
    return '<tr style="animation:rowin .4s ease-out both;animation-delay:' + (i * 60) + 'ms">' +
      "<td>" + (m.qty > 1 ? '<b>' + m.qty + "×</b> " : "") + esc(m.product.name) +
        (m.ambiguous && m.ambiguous.length ? '<div class="small muted">זוהה מתוך "' + esc(m.desc) + '"</div>' : "") + "</td>" +
      '<td class="tnum">' + paidLine + "</td>" +
      '<td class="tnum" style="color:var(--green-link);font-weight:800">' + (cheapest ? nis(cheapest.price) + " ₪" : "—") + "</td>" +
      '<td class="small col-opt">' + (atBest ? nis(atBest.price) + " ₪" : '<span class="muted">לא נמכר שם</span>') + "</td>" +
      '<td class="tnum col-opt" style="color:' + gapCol + ';font-weight:800">' + (gap == null ? "—" : (gap > 0 ? "חסכון " + nis(gap) : nis(Math.abs(gap)) + " ₪ יקר יותר")) + "</td></tr>";
  }).join("");

  return '<div class="wrap" style="display:flex;flex-direction:column;gap:20px">' +
    '<div style="background:var(--ink);color:#fff;border:3px solid var(--ink);border-radius:22px;padding:26px;box-shadow:8px 8px 0 var(--green);display:flex;flex-wrap:wrap;gap:24px;align-items:center">' +
      (paid != null ?
        '<div><div class="small" style="color:var(--muted-dark);font-weight:700">שילמתם על ' + r.paid_known + ' פריטים שזוהו</div>' +
        '<div class="tnum" style="font-size:44px;font-weight:900;text-decoration:line-through;text-decoration-color:var(--red);text-decoration-thickness:5px">' + nis(paid) + " ₪</div></div>" : "") +
      '<div><div class="small" style="color:var(--muted-dark);font-weight:700">אותו סל ב' + esc(best.chain) + " · " + esc(best.branch) + '</div>' +
        '<div class="tnum" style="font-size:44px;font-weight:900;color:var(--green)"><span data-count="' + bestTotal + '" data-key="scanbest">' + nis(bestTotal) + "</span> ₪</div></div>" +
      (saving != null && saving > 0 ?
        '<div class="pill" style="background:var(--yellow);border:3px solid var(--ink);color:var(--ink);font-weight:900;transform:rotate(-2deg);font-size:15px">שילמתם ' + nis(saving) + " ₪ יותר · " + (paid ? (saving / paid * 100).toFixed(1) : 0) + "% מהסל</div>" : "") +
    "</div>" +
    (r.unmatched.length ? '<div class="warn">' + r.unmatched.length + " שורות לא זוהו ולא נכללו בחישוב: " + esc(r.unmatched.slice(0, 8).map(function (u) { return u.desc; }).join(" · ")) + "</div>" : "") +
    '<div class="card" style="overflow-x:auto"><table class="tbl-opt"><thead><tr><th>מוצר</th><th>שילמתם</th><th>הזול בארץ</th><th class="col-opt">ב' + esc(best.chain) + '</th><th class="col-opt">הפרש</th></tr></thead><tbody>' + rows + "</tbody></table>" +
      '<div class="note" style="margin-top:12px">' + esc(freshnessNote()) + "</div></div>" +
    '<div style="display:flex;gap:12px;flex-wrap:wrap">' +
      '<button class="btn btn-ink" data-scan-tocart>טענו את הסל ותכננו את הקנייה הבאה ←</button>' +
      '<button class="btn" data-scan-reset>בדקו קבלה אחרת</button></div></div>';
}

// ------------------------------------------------------------------ cart
function screenCart() {
  if (!S.cart.length) {
    return '<div class="wrap"><h1 style="font-size:32px;font-weight:900">🛒 הסל שלי</h1>' +
      '<div class="card" style="margin-top:16px;text-align:center;padding:40px">הסל ריק. <a data-go="home">חפשו מוצרים</a> והוסיפו אותם לסל.</div></div>';
  }
  var d = S.cartData;
  var items = S.cart.map(function (it) {
    var live = d && d.items ? d.items.filter(function (x) { return x.barcode === it.barcode; })[0] : null;
    return '<div style="display:flex;align-items:center;gap:14px;padding:14px 18px;border-bottom:2px solid var(--div);flex-wrap:wrap">' +
      '<div style="width:52px;height:52px;border-radius:12px;flex:none;background:' + (it.tint || "#eee") + ';border:2px solid var(--ink)"></div>' +
      '<div style="flex:1 1 160px;min-width:0"><div style="font-size:16px;font-weight:800">' + esc(it.name) + "</div>" +
        '<div class="small muted">' + (live && live.found ?
          '<span style="color:var(--green-link);font-weight:800">' + nis(live.min) + '</span> – <span style="color:var(--red);font-weight:800">' + nis(live.max) + "</span> ₪ · " + num(live.stores) + " סניפים" :
          (d ? "לא נמצא בסניפים שתואמים לסינון" : "טוען…")) + "</div></div>" +
      '<div class="qty"><button data-qty="' + esc(it.barcode) + '" data-delta="-1">−</button>' +
        '<span style="min-width:22px;text-align:center;font-weight:900" class="tnum">' + it.qty + "</span>" +
        '<button data-qty="' + esc(it.barcode) + '" data-delta="1">+</button></div>' +
      '<button style="border:0;background:none;color:var(--muted);font-size:13px;font-weight:700;padding:6px" data-remove="' + esc(it.barcode) + '">הסר</button></div>';
  }).join("");

  var cityOpts = ['<option value="">כל הארץ</option>'].concat(S.cities.map(function (c) {
    return '<option value="' + esc(c.name) + '"' + (S.city === c.name ? " selected" : "") + ">" + esc(c.name) + " (" + c.stores + ")</option>";
  })).join("");

  var right = '<div class="card"><div class="loading"><span class="spinner"></span> מחשבים…</div></div>';
  var totals = "";
  if (d && !d.error) {
    if (d.best) {
      var b = d.best;
      var worst = d.chain_totals.length ? d.chain_totals[d.chain_totals.length - 1] : null;
      var saveVsWorst = worst ? worst.total - b.total : 0;
      right = '<div style="display:flex;flex-direction:column;gap:16px">' +
        '<div class="card" style="background:var(--green);box-shadow:6px 6px 0 var(--ink)">' +
          '<div style="font-size:13px;font-weight:800">🏆 הסניף הזול לכל הסל</div>' +
          '<div style="font-size:26px;font-weight:900;margin-top:6px">' + esc(b.chain) + "</div>" +
          '<div class="small" style="font-weight:600;color:var(--green-dark)">' + esc(b.branch) + " · " + esc(b.city) + "</div>" +
          (b.address && b.address !== UNKNOWN ? '<div class="small" style="color:var(--green-dark)">' + esc(b.address) + "</div>" : "") +
          '<div class="tnum" style="font-size:44px;font-weight:900;margin-top:10px"><span data-count="' + b.total + '" data-key="carttotal">' + nis(b.total) + "</span> ₪</div>" +
          (saveVsWorst > 0 ? '<div class="pill" style="background:#fff;width:fit-content;margin-top:8px;font-weight:800">חוסך ' + nis(saveVsWorst) + " ₪ מול היקר ביותר</div>" : "") +
          '<div class="note" style="margin-top:8px;color:var(--green-dark)">מחירים מ־' + b.dates.map(dateHe).join(", ") + (b.complete ? "" : " · הסניף מוכר " + b.items + " מתוך " + d.available + " המוצרים") + "</div>" +
          (b.note ? '<div class="note" style="color:var(--green-dark)">ⓘ ' + esc(b.note) + "</div>" : "") +
        "</div>" +
        receiptCard(b, d) +
        (d.split.length > 1 ? splitCard(d) : "") +
      "</div>";

      var mx = d.chain_totals.length ? d.chain_totals[d.chain_totals.length - 1].total : 1;
      totals = '<div class="card"><h3 class="h3">כמה עולה אותו סל בכל רשת</h3>' +
        '<div style="display:flex;flex-direction:column;gap:8px;margin-top:14px">' +
        d.chain_totals.map(function (c, i) {
          return '<div style="display:grid;grid-template-columns:120px 1fr 90px;gap:10px;align-items:center;font-size:13px">' +
            '<span style="font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(c.chain) + "</span>" +
            '<div style="height:18px;position:relative"><div style="position:absolute;right:0;top:0;bottom:0;width:' + (c.total / mx * 100).toFixed(0) + "%;background:" + c.color + ";border:2px solid var(--ink);border-radius:4px;animation:meter .6s ease-out both;animation-delay:" + (i * 60) + 'ms"></div></div>' +
            '<span class="tnum" style="text-align:left;font-weight:900">' + nis(c.total) + " ₪</span></div>";
        }).join("") + "</div>" +
        '<div class="note" style="margin-top:12px">מוצג רק סניף אחד לכל רשת - הזול ביותר שמוכר את כל ' + d.available + " המוצרים.</div></div>";
    } else {
      right = '<div class="card"><h3 class="h3">אין סניף שמוכר את כל הסל</h3><p class="note" style="margin-top:8px">נסו להסיר מוצר או לבטל את סינון העיר.</p></div>';
    }
  }

  var missing = d && d.missing && d.missing.length ?
    '<div class="warn">' + d.missing.length + " מוצרים לא נמצאו בסניפים שתואמים לסינון ולא נכללו בחישוב.</div>" : "";

  var meter = "";
  if (d && d.chain_totals && d.chain_totals.length > 1) {
    var lo = d.chain_totals[0].total, hi = d.chain_totals[d.chain_totals.length - 1].total;
    meter = '<div class="card" style="background:var(--ink);color:#fff;position:relative;overflow:hidden">' +
      '<div style="position:absolute;width:180px;height:180px;background:var(--purple);right:-60px;top:-90px;animation:blob 8s ease-in-out infinite;opacity:.8"></div>' +
      '<div style="position:relative"><div style="font-size:18px;font-weight:900">מד חיסכון: כמה הסל הזה יכול לעלות</div>' +
      '<div style="font-size:28px;font-weight:900;color:var(--yellow);margin:8px 0">' + pctStr((hi - lo) / lo * 100) + " פער</div>" +
      '<div class="meter-bar"></div>' +
      '<div style="display:flex;justify-content:space-between;margin-top:8px" class="tnum"><span style="color:var(--green);font-size:24px;font-weight:900">' + nis(lo) + " ₪</span>" +
      '<span style="color:var(--red);font-size:24px;font-weight:900">' + nis(hi) + " ₪</span></div></div></div>";
  }

  return '<div class="wrap" style="display:flex;flex-wrap:wrap;gap:20px;align-items:flex-start;max-width:1240px">' +
    '<section style="flex:999 1 460px;min-width:0;display:flex;flex-direction:column;gap:16px">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">' +
        '<h1 style="font-size:32px;font-weight:900">🛒 הסל שלי</h1>' +
        '<div style="display:flex;gap:10px;align-items:center"><select id="citysel" style="border:2px solid var(--ink);border-radius:12px;padding:8px 10px;font-weight:600">' + cityOpts + "</select>" +
        '<span class="pill" style="background:var(--ink);color:#fff">' + cartCount() + " פריטים</span></div></div>" +
      '<div class="card" style="padding:0;overflow:hidden">' + items + "</div>" +
      missing + meter + totals +
    "</section>" +
    '<aside style="flex:1 1 300px;min-width:0;position:sticky;top:12px">' + right + "</aside></div>";
}

function receiptCard(b, d) {
  var lines = "";
  (d.best_items || []).forEach(function (it) {
    lines += '<div style="display:flex;justify-content:space-between;gap:8px"><span>' +
      (it.qty > 1 ? it.qty + "× " : "") + esc(it.name.slice(0, 22)) + "</span><span>" +
      (it.total == null ? "לא נמכר" : nis(it.total)) + "</span></div>";
  });
  return '<div class="receipt"><div style="text-align:center;font-weight:800">' + esc(b.chain) + "<br>" + esc(b.branch) + "</div>" +
    '<div class="rdiv"></div>' + lines + '<div class="rdiv"></div>' +
    '<div style="display:flex;justify-content:space-between;font-weight:800;font-size:14px"><span>סה״כ</span><span>' + nis(b.total) + " ₪</span></div>" +
    '<div style="margin-top:10px;height:24px;background:repeating-linear-gradient(90deg,var(--ink) 0 2px,transparent 2px 4px,var(--ink) 4px 5px,transparent 5px 8px)"></div>' +
    '<div style="text-align:center;font-size:10px;margin-top:4px">' + b.dates.map(dateHe).join(" · ") + "</div>" +
    '<div class="serrate" style="margin:10px -16px -16px"></div></div>';
}

function splitCard(d) {
  var stores = d.split.slice(0, 3);
  return '<div class="card" style="box-shadow:6px 6px 0 var(--yellow)">' +
    '<div style="font-size:16px;font-weight:900">פיצול בין ' + d.split.length + " חנויות</div>" +
    (d.split_saving > 0.005 ? '<div class="pill" style="background:var(--green);width:fit-content;margin-top:8px;font-weight:800">חוסך עוד ' + nis(d.split_saving) + " ₪</div>" :
      '<div class="note" style="margin-top:8px">הפיצול לא חוסך יותר מקנייה בסניף אחד.</div>') +
    '<div style="display:flex;flex-direction:column;gap:10px;margin-top:12px">' +
      stores.map(function (s) {
        return '<div style="border-top:2px dashed var(--div2);padding-top:8px"><div style="font-weight:800;font-size:14px">' + esc(s.store.chain) + " · " + esc(s.store.branch) + "</div>" +
          '<div class="small muted">' + esc(s.store.city) + " · " + s.items.length + " מוצרים · " + nis(s.total) + " ₪</div></div>";
      }).join("") + "</div>" +
    '<div class="tnum" style="font-size:22px;font-weight:900;margin-top:12px">סה״כ ' + nis(d.split_total) + " ₪</div></div>";
}

// ------------------------------------------------------------------ render
function render() {
  var body;
  if (S.screen === "home") body = screenHome();
  else if (S.screen === "product") body = screenProduct();
  else if (S.screen === "market") body = screenMarket();
  else if (S.screen === "scan") body = screenScan();
  else body = screenCart();

  var toastHtml = S.toast ? '<div style="position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:var(--ink);color:#fff;padding:12px 20px;border-radius:14px;font-weight:800;z-index:99;box-shadow:5px 5px 0 var(--green)">' + esc(S.toast) + "</div>" : "";
  document.getElementById("app").innerHTML = header() + tape() + body + mobileNav() + toastHtml;
  runCountUps();
}

// ------------------------------------------------------------------ actions
// כתובת לכל מצב, כדי שכפתור "אחורה", רענון ושיתוף קישור יעבדו
function hashFor(screen, barcode) {
  return screen === "product" && barcode ? "#product/" + encodeURIComponent(barcode) : "#" + screen;
}

function go(screen, opts) {
  opts = opts || {};
  S.screen = screen;
  S.focused = false;
  window.scrollTo(0, 0);
  if (screen === "market" && !S.market) loadMarket();
  if (screen === "cart") loadCart2();
  setHash(hashFor(screen), opts.replace);
  render();
}

var suppressHash = false;
function setHash(h, replace) {
  if (location.hash === h) return;
  suppressHash = true;
  if (replace) history.replaceState(null, "", h);
  else history.pushState(null, "", h);
  setTimeout(function () { suppressHash = false; }, 0);
}

// קורא את הכתובת ומציג את המצב שהיא מתארת
function applyHash(initial) {
  var h = (location.hash || "").replace(/^#/, "");
  var m = /^product\/(.+)$/.exec(h);
  if (m) {
    var code = decodeURIComponent(m[1]);
    if (S.screen === "product" && S.productBarcode === code && S.product) return;
    S.screen = "product"; S.productBarcode = code; S.product = null; S.chains = null;
    render(); loadProduct();
    return;
  }
  var screen = ["home", "market", "scan", "cart"].indexOf(h) >= 0 ? h : "home";
  if (!initial && screen === S.screen) { render(); return; }
  S.screen = screen;
  S.focused = false;
  if (screen === "market" && !S.market) loadMarket();
  if (screen === "cart") loadCart2();
  render();
}

window.addEventListener("popstate", function () { if (!suppressHash) applyHash(false); });
window.addEventListener("hashchange", function () { if (!suppressHash) applyHash(false); });

function openProduct(barcode) {
  S.screen = "product";
  S.productBarcode = barcode;
  S.product = null;
  S.chains = null;
  S.focused = false;
  window.scrollTo(0, 0);
  setHash(hashFor("product", barcode));
  render();
  loadProduct();
}

function loadProduct() {
  API.product({ barcode: S.productBarcode, city: S.city, chains: S.chains, includeOld: S.includeOld })
    .then(function (d) { S.product = d; render(); })
    .catch(function (e) { S.product = { error: e.message }; render(); });
}

function loadMarket() {
  API.market(S.marketBarcode)
    .then(function (d) { S.market = d; if (d.selected) S.marketBarcode = d.selected.barcode; render(); })
    .catch(function (e) { toast(e.message); });
}

function loadCart2() {
  if (!S.cart.length) { S.cartData = null; return; }
  S.cartData = null;
  API.basket(S.cart.map(function (c) { return { barcode: c.barcode, qty: c.qty }; }), S.city)
    .then(function (d) { S.cartData = d; render(); })
    .catch(function (e) { toast(e.message); });
}

function addToCart(barcode, name, tint) {
  var ex = S.cart.filter(function (c) { return c.barcode === barcode; })[0];
  if (ex) { ex.qty++; } else { S.cart.push({ barcode: barcode, name: name, tint: tint, qty: 1 }); }
  saveCart();
  S.burst = true;
  render();
  setTimeout(function () { S.burst = false; if (S.screen === "product") render(); }, 1000);
}

var doSuggest = debounce(function () {
  var v = S.query.trim();
  if (!v) { S.suggestions = []; S.searchedFor = ""; S.searchError = null; paintSuggest(); return; }
  API.search(v, 6).then(function (d) {
    if (S.query.trim() !== v) return;      // תשובה מאיחור על הקלדה ישנה
    S.suggestions = d.results;
    S.searchedFor = v;
    S.searchError = null;
    if (S.focused) paintSuggest();
  }).catch(function (e) {
    if (S.query.trim() !== v) return;
    S.suggestions = [];
    S.searchError = e && e.message ? e.message : String(e);
    if (S.focused) paintSuggest();
  });
}, 220);

function runSearch() {
  var v = S.query.trim();
  if (!v) return;
  S.searchError = null;
  API.search(v, 40).then(function (d) {
    if (d.results.length === 1) { openProduct(d.results[0].barcode); return; }
    S.suggestions = d.results;
    S.searchedFor = v;
    S.focused = true;
    paintSuggest();
    if (!d.results.length) toast('לא נמצאו מוצרים ל־"' + v + '"');
  }).catch(function (e) {
    // כשל שקט הוא הגרוע מכל: המשתמש לוחץ ולא קורה כלום
    S.suggestions = [];
    S.searchError = e && e.message ? e.message : String(e);
    S.focused = true;
    paintSuggest();
    toast("החיפוש נכשל. נסו שוב.");
  });
}

function runScan() {
  var txt = (document.getElementById("scantext") || {}).value || "";
  if (!txt.trim()) { toast("הדביקו קודם את שורות הקבלה"); return; }
  S.scanText = txt;
  S.scanPhase = "scanning";
  render();
  API.receipt(txt, S.city)
    .then(function (d) { S.scanResult = d; S.scanPhase = "done"; window.scrollTo(0, 0); render(); })
    .catch(function (e) { S.scanPhase = "idle"; toast(e.message); render(); });
}

function sampleReceipt() {
  var pop = (S.home && S.home.popular) || [];
  if (!pop.length) { toast("עוד רגע, הנתונים נטענים"); return; }
  var lines = pop.slice(0, 5).map(function (p, i) {
    var paid = (p.median * (i === 0 ? 1.18 : 1.05)).toFixed(2);
    return (i === 1 ? "2 x " : "") + p.name + "   " + paid;
  });
  S.scanText = lines.join("\n");
  var el = document.getElementById("scantext");
  if (el) el.value = S.scanText;
  toast("מולאה דוגמה ממוצרים אמיתיים במסד. המחירים בה הם המחשה בלבד.");
}

// ------------------------------------------------------------------ events
document.addEventListener("click", function (ev) {
  var t = ev.target.closest("[data-go],[data-open],[data-add],[data-mkt],[data-range],[data-chain],[data-allchains],[data-qty],[data-remove],[data-search],[data-scan-run],[data-scan-sample],[data-scan-reset],[data-scan-tocart],[data-toggle-old],[data-clear-filters],[data-filter-toggle]");
  if (!t) {
    if (S.focused && !ev.target.closest(".searchbox") && !ev.target.closest(".suggest")) { S.focused = false; paintSuggest(); }
    return;
  }
  if (t.hasAttribute("data-filter-toggle")) { S.filterOpen = !S.filterOpen; render(); return; }
  if (t.hasAttribute("data-go")) { go(t.getAttribute("data-go")); return; }
  if (t.hasAttribute("data-open")) { openProduct(t.getAttribute("data-open")); return; }
  if (t.hasAttribute("data-search")) { runSearch(); return; }
  if (t.hasAttribute("data-add")) {
    var p = S.product.product;
    addToCart(p.barcode, p.name, p.tint);
    return;
  }
  if (t.hasAttribute("data-mkt")) { S.marketBarcode = t.getAttribute("data-mkt"); S.market = null; render(); loadMarket(); return; }
  if (t.hasAttribute("data-range")) { S.range = t.getAttribute("data-range"); render(); return; }
  if (t.hasAttribute("data-chain")) {
    var c = t.getAttribute("data-chain");
    var all = S.product.all_chains;
    if (!S.chains) S.chains = all.slice();
    var i = S.chains.indexOf(c);
    if (i >= 0) S.chains.splice(i, 1); else S.chains.push(c);
    if (!S.chains.length) S.chains = all.slice();
    S.product = null; render(); loadProduct(); return;
  }
  if (t.hasAttribute("data-allchains")) { S.chains = null; S.product = null; render(); loadProduct(); return; }
  if (t.hasAttribute("data-toggle-old")) { S.includeOld = !S.includeOld; S.product = null; render(); loadProduct(); return; }
  if (t.hasAttribute("data-clear-filters")) { S.city = ""; S.chains = null; S.includeOld = false; S.product = null; render(); loadProduct(); return; }
  if (t.hasAttribute("data-qty")) {
    var bc = t.getAttribute("data-qty"), dl = parseInt(t.getAttribute("data-delta"), 10);
    S.cart.forEach(function (it) { if (it.barcode === bc) it.qty = Math.max(1, it.qty + dl); });
    saveCart(); render(); loadCart2(); return;
  }
  if (t.hasAttribute("data-remove")) {
    S.cart = S.cart.filter(function (it) { return it.barcode !== t.getAttribute("data-remove"); });
    saveCart(); render(); loadCart2(); return;
  }
  if (t.hasAttribute("data-scan-run")) { runScan(); return; }
  if (t.hasAttribute("data-scan-sample")) { sampleReceipt(); return; }
  if (t.hasAttribute("data-scan-reset")) { S.scanPhase = "idle"; S.scanResult = null; render(); return; }
  if (t.hasAttribute("data-scan-tocart")) {
    S.scanResult.matched.forEach(function (m) {
      var ex = S.cart.filter(function (c) { return c.barcode === m.product.barcode; })[0];
      if (ex) ex.qty += Math.max(1, Math.round(m.qty));
      else S.cart.push({ barcode: m.product.barcode, name: m.product.name, tint: m.product.tint, qty: Math.max(1, Math.round(m.qty)) });
    });
    saveCart(); go("cart"); return;
  }
});

document.addEventListener("input", function (ev) {
  if (ev.target.id === "q") { S.query = ev.target.value; doSuggest(); }
  if (ev.target.id === "scantext") { S.scanText = ev.target.value; }
});
document.addEventListener("focusin", function (ev) {
  if (ev.target.id === "q" && !S.focused) { S.focused = true; paintSuggest(); if (S.query.trim()) doSuggest(); }
});
document.addEventListener("keydown", function (ev) {
  if (ev.key === "Enter" && ev.target.id === "q") { ev.preventDefault(); runSearch(); }
  if (ev.key === "Escape" && S.focused) { S.focused = false; paintSuggest(); }
});
document.addEventListener("change", function (ev) {
  if (ev.target.id === "citysel") {
    S.city = ev.target.value;
    try { localStorage.setItem(LS_CITY, S.city); } catch (e) {}
    if (S.screen === "product") { S.product = null; render(); loadProduct(); }
    else { render(); loadCart2(); }
  }
  if (ev.target.id === "scanfile" && ev.target.files && ev.target.files[0]) {
    var fr = new FileReader();
    fr.onload = function () {
      S.scanText = String(fr.result || "");
      var el = document.getElementById("scantext"); if (el) el.value = S.scanText;
      toast("הקובץ נטען. לחצו על \"בדקו את הקבלה\".");
    };
    fr.readAsText(ev.target.files[0]);
  }
});
document.addEventListener("mousemove", function (ev) {
  var hero = document.getElementById("hero");
  if (!hero || S.screen !== "home") return;
  var r = hero.getBoundingClientRect();
  if (ev.clientY > r.bottom) return;
  var nx = (ev.clientX / window.innerWidth) - .5, ny = (ev.clientY / r.height) - .5;
  S.mx = nx; S.my = ny;
  hero.querySelectorAll(".hero-layer").forEach(function (el, i) {
    el.style.transform = i === 0 ? "translate(" + (nx * -30) + "px," + (ny * -20) + "px)" : "translate(" + (nx * 40) + "px," + (ny * 30) + "px)";
  });
});

// ------------------------------------------------------------------ boot
function boot(msg) {
  document.getElementById("app").innerHTML =
    '<div class="boot"><span class="spinner"></span> ' + esc(msg) + "</div>";
}

loadCart();
API = window.MehironData();
boot("מתחיל…");
API.init(boot)
  .then(function () {
    boot("טוען מחירים…");
    return Promise.all([
      API.home(),
      API.meta(),
      fetch("cities_geo.json").then(function (r) { return r.json(); }).catch(function () { return {}; })
    ]);
  })
  .then(function (res) {
    S.home = res[0];
    S.meta = res[1].meta;
    S.cities = res[1].cities;
    S.geo = res[2] || {};
    applyHash(true);
  })
  .catch(function (e) {
    document.getElementById("app").innerHTML =
      '<div class="boot">לא הצלחנו לטעון את הנתונים.<br><span style="font-size:13px">' + esc(e && e.message ? e.message : e) + "</span></div>";
  });
})();
