# -*- coding: utf-8 -*-
"""
מחירון - שרת האפליקציה.

מגיש את האתר ואת ה-API מעל prices.db. ללא ספריות חיצוניות.
הפעלה: python server.py  [--port 8000] [--host 127.0.0.1]
"""
import argparse
import datetime as dt
import json
import mimetypes
import os
import re
import sqlite3
import statistics
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# ממשק אחד משותף לשרת המקומי ולאתר בענן. ההבדל היחיד הוא config.js,
# שהשרת מייצר בעצמו כדי להורות ל-data.js לקרוא ל-API במקום למסד בענן.
STATIC_DIR = os.path.join(os.path.dirname(BASE_DIR), "site")
LOCAL_CONFIG = (
    "/* config for the local server: data comes from /api, not the cloud */\n"
    'window.MEHIRON_CONFIG = { mode: \"server\" };\n'
)
DB_PATH = os.path.join(os.path.dirname(BASE_DIR), "prices.db")
CITIES_PATH = os.path.join(os.path.dirname(BASE_DIR), "cities.json")

UNKNOWN = "לא ידוע"
NOTE_NO_STORE_FILE = "הרשת לא מפרסמת קובץ סניפים"
FRESH_DAYS = 7          # חלון טריות ברירת מחדל להשוואות
TINTS = ["#bfe9ff", "#ffd9e8", "#ffe9a8", "#d6f5c9", "#e3dcff", "#ffd6c2", "#c9f2ee", "#fff0c2"]
HEAT = ["#1fb85a", "#7fd63a", "#ffcb3d", "#ff9a3d", "#ff6a4d", "#ff4d4d"]

_local = threading.local()


# ------------------------------------------------------------------ database
def db():
    """חיבור לקריאה בלבד, אחד לכל תהליכון."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        uri = "file:" + DB_PATH.replace("\\", "/").replace("?", "%3f").replace("#", "%23") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA cache_size=-80000")
        _local.conn = conn
    return conn


def q(sql, params=()):
    return db().execute(sql, params).fetchall()


def q1(sql, params=()):
    return db().execute(sql, params).fetchone()


# ------------------------------------------------------------------ helpers
def tint_for(barcode):
    digits = "".join(ch for ch in str(barcode) if ch.isdigit()) or "0"
    return TINTS[int(digits[-2:] or 0) % len(TINTS)]


def heat_color(idx, total):
    if total <= 1:
        return HEAT[0]
    pos = idx / (total - 1) * (len(HEAT) - 1)
    return HEAT[int(round(pos))]


_latest_cache = {"at": 0, "date": None}


def latest_data_date():
    """התאריך האחרון שיש בנתונים. נמדד ממנו חלון הטריות, ולא מהיום."""
    now = dt.datetime.now().timestamp()
    if _latest_cache["date"] and now - _latest_cache["at"] < 300:
        return _latest_cache["date"]
    row = q1("SELECT value v FROM app_meta WHERE key = 'latest_date'")
    d = (row["v"] if row else None) or dt.date.today().isoformat()
    _latest_cache.update(at=now, date=d)
    return d


def fresh_cutoff():
    return (dt.date.fromisoformat(latest_data_date()) - dt.timedelta(days=FRESH_DAYS)).isoformat()


def load_cities():
    try:
        with open(CITIES_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


CBS_CITIES = load_cities()
CBS_NAMES = set(CBS_CITIES.values())


def canon_key(name):
    """מפתח השוואה לשמות יישובים: מאחד קרית/קריית, מקפים ורווחים כפולים."""
    s = (name or "").strip()
    s = s.replace("־", "-").replace("–", "-")
    s = re.sub(r"\s*-\s*", " - ", s)
    s = re.sub(r"\s+", " ", s)
    s = s.replace("קרית ", "קריית ")
    return s


# שמות שונים שהרשתות מפרסמות לאותו יישוב, ממופים לשם הרשמי של הלמ"ס.
# מיפוי מחרוזות בלבד (איות/מקף) - לא ניחוש של עיר חסרה.
_ALIAS = {}
for _cbs in CBS_NAMES:
    _ALIAS.setdefault(canon_key(_cbs), _cbs)
    _short = _cbs.split(" - ")[0].strip()
    if _short != _cbs:
        _ALIAS.setdefault(canon_key(_short), _cbs)


def city_display(raw):
    """
    שם עיר להצגה. מחזיר (שם, הערה).
    מספר שאינו קוד יישוב מוכר, או ערך ריק, מוצג כ"לא ידוע" עם הסבר.
    """
    raw = (raw or "").strip()
    if not raw or raw == UNKNOWN:
        return UNKNOWN, "העיר חסרה בקובץ הרשת"
    if raw.isdigit():
        name = CBS_CITIES.get(str(int(raw)))
        if name:
            return name, ""
        return UNKNOWN, f"הרשת פרסמה קוד יישוב שאינו מוכר ({raw})"
    return _ALIAS.get(canon_key(raw), raw), ""


def city_group(raw):
    """מפתח קיבוץ לעיר, לצורך סינון ורשימות."""
    name, _note = city_display(raw)
    return name


def money(v):
    return round(float(v), 2)


def pct(a, b):
    return round((a - b) / b * 100, 1) if b else 0.0


# ------------------------------------------------------------------ metadata
_meta_cache = {"at": 0, "data": None}


def data_meta():
    """מצב הנתונים: תאריך אחרון, מספרי סניפים ורשתות, ומה חסר."""
    now = dt.datetime.now().timestamp()
    if _meta_cache["data"] and now - _meta_cache["at"] < 300:
        return _meta_cache["data"]
    kv = {r["key"]: r["value"] for r in q("SELECT key, value FROM app_meta")}
    cutoff = fresh_cutoff()
    latest = kv.get("latest_date")
    chains = []
    for r in q("SELECT * FROM chain_stats ORDER BY chain"):
        chains.append({
            "name": r["chain"], "stores": r["stores"], "rows": r["rows"],
            "from": r["date_min"], "to": r["date_max"], "stale": (r["date_max"] or "") < cutoff,
            "note": "" if r["has_store_file"] else NOTE_NO_STORE_FILE,
        })
    data = {
        "latest_date": latest,
        "fresh_from": cutoff,
        "fresh_days": FRESH_DAYS,
        "stores_today": int(kv.get("stores_today") or 0),
        "stores_total": int(kv.get("stores_total") or 0),
        "products": q1("SELECT COUNT(*) n FROM product_stats")["n"],
        "price_rows": int(kv.get("price_rows") or 0),
        "chains": chains,
        "index_built_at": kv.get("index_built_at"),
        "unknown_city_stores": (q1("SELECT stores n FROM city_stats WHERE city = ?", (UNKNOWN,)) or {"n": 0})["n"],
    }
    _meta_cache.update(at=now, data=data)
    return data


_cities_cache = {"at": 0, "data": None}


def city_list():
    now = dt.datetime.now().timestamp()
    if _cities_cache["data"] and now - _cities_cache["at"] < 600:
        return _cities_cache["data"]
    counts = {}
    for r in q("SELECT city, stores n FROM city_stats"):
        name = city_group(r["city"])
        counts[name] = counts.get(name, 0) + r["n"]
    known = sorted(((c, n) for c, n in counts.items() if c != UNKNOWN), key=lambda x: -x[1])
    out = [{"name": c, "stores": n} for c, n in known]
    if UNKNOWN in counts:
        out.append({"name": UNKNOWN, "stores": counts[UNKNOWN]})
    _cities_cache.update(at=now, data=out)
    return out


def city_raw_values(city):
    """כל האיותים הגולמיים שמייצגים את העיר המבוקשת."""
    if not city:
        return None
    vals = []
    for r in q("SELECT city FROM city_stats"):
        if city_group(r["city"]) == city:
            vals.append(r["city"])
    return vals


# ------------------------------------------------------------------ products
def product_row(barcode):
    return q1("SELECT * FROM product_stats WHERE barcode = ?", (barcode,))


def store_meta(chain, store_id):
    r = q1("SELECT store_name, city, address, notes FROM stores WHERE chain = ? AND store_id = ?",
           (chain, store_id))
    if not r:
        return {"branch": f"סניף {store_id}", "city": UNKNOWN, "address": UNKNOWN,
                "note": NOTE_NO_STORE_FILE}
    city, note = city_display(r["city"])
    notes = [n for n in [(r["notes"] or ""), note] if n]
    return {"branch": r["store_name"] or f"סניף {store_id}", "city": city,
            "address": r["address"] or UNKNOWN, "note": "; ".join(dict.fromkeys(notes))}


def product_brief(row):
    return {
        "barcode": row["barcode"],
        "name": row["name"] or UNKNOWN,
        "tint": tint_for(row["barcode"]),
        "min": money(row["min_price"]),
        "max": money(row["max_price"]),
        "median": money(row["median"]),
        "gap_pct": round(row["gap_pct"], 1),
        "gap_shekel": money(row["max_price"] - row["min_price"]),
        "stores": row["n_stores"],
        "chains": row["n_chains"],
        "min_chain": row["min_chain"],
        "max_chain": row["max_chain"],
        "min_date": row["min_date"],
        "max_date": row["max_date"],
    }


def spark_for(barcode, points=6):
    """סדרת נקודות אמיתית מ-market_daily; אם אין נתוני עבר מחזיר רשימה ריקה."""
    rows = q(
        "SELECT date, median FROM market_daily WHERE barcode = ? ORDER BY date DESC LIMIT ?",
        (barcode, points),
    )
    if len(rows) < 2:
        return []
    vals = [r["median"] for r in rows][::-1]
    return [money(v) for v in vals]


# ------------------------------------------------------------------ endpoints
def api_meta(_p):
    m = data_meta()
    return {"meta": m, "cities": city_list()}


def api_home(_p):
    meta = data_meta()
    popular = []
    for r in q(
        """
        SELECT * FROM product_stats
        WHERE name IS NOT NULL AND name <> '' AND n_stores >= 300 AND gap_pct > 0
        ORDER BY n_stores DESC LIMIT 60
        """
    ):
        popular.append(product_brief(r))
    popular.sort(key=lambda p: -p["gap_pct"])
    top = popular[:8]
    for p in top:
        p["spark"] = spark_for(p["barcode"])

    deal = None
    if top:
        d = dict(top[0])
        lo = store_meta(d["min_chain"], product_row(d["barcode"])["min_store"])
        hi = store_meta(d["max_chain"], product_row(d["barcode"])["max_store"])
        d["min_store"] = lo
        d["max_store"] = hi
        deal = d

    ticker = []
    for r in q(
        """
        SELECT md.barcode, md.date, md.median, ps.name FROM market_daily md
        JOIN market_products mp ON mp.barcode = md.barcode
        JOIN product_stats ps ON ps.barcode = md.barcode
        WHERE md.date = (SELECT MAX(date) FROM market_daily WHERE barcode = md.barcode)
        ORDER BY mp.rank LIMIT 14
        """
    ):
        prev = q1(
            "SELECT median FROM market_daily WHERE barcode = ? AND date < ? ORDER BY date DESC LIMIT 1",
            (r["barcode"], r["date"]),
        )
        chg = pct(r["median"], prev["median"]) if prev else None
        ticker.append({
            "barcode": r["barcode"], "name": r["name"], "price": money(r["median"]),
            "change": chg, "date": r["date"],
        })
    return {"meta": meta, "popular": top, "deal": deal, "ticker": ticker,
            "quick": [{"barcode": p["barcode"], "name": p["name"], "tint": p["tint"]} for p in popular[:5]]}


def _fts_query(text):
    words = [w for w in re.split(r"[^\w֐-׿%]+", text) if w]
    return " ".join(f'"{w}"*' for w in words)


def search_products(text, limit=30):
    text = (text or "").strip()
    if not text:
        return []
    if text.isdigit() and len(text) >= 4:
        rows = q(
            "SELECT * FROM product_stats WHERE barcode LIKE ? ORDER BY n_stores DESC LIMIT ?",
            (text + "%", limit),
        )
        if rows:
            return [product_brief(r) for r in rows]
    try:
        rows = q(
            """
            SELECT ps.* FROM product_fts f JOIN product_stats ps ON ps.barcode = f.barcode
            WHERE product_fts MATCH ? ORDER BY ps.n_stores DESC LIMIT ?
            """,
            (_fts_query(text), limit),
        )
    except sqlite3.OperationalError:
        rows = []
    if not rows:
        words = [w for w in text.split() if w]
        where = " AND ".join("name LIKE ?" for _ in words) or "name LIKE ?"
        params = [f"%{w}%" for w in words] or [f"%{text}%"]
        rows = q(
            f"SELECT * FROM product_stats WHERE {where} ORDER BY n_stores DESC LIMIT ?",
            params + [limit],
        )
    return [product_brief(r) for r in rows]


def api_search(p):
    return {"query": p.get("q", [""])[0], "results": search_products(p.get("q", [""])[0],
                                                                    int(p.get("limit", ["30"])[0]))}


def api_product(p):
    barcode = p.get("barcode", [""])[0]
    city = (p.get("city", [""])[0] or "").strip()
    chains = [c for c in (p.get("chains", [""])[0] or "").split("|") if c]
    include_old = p.get("include_old", ["0"])[0] == "1"

    row = product_row(barcode)
    if not row:
        return {"error": "המוצר לא נמצא"}

    where = ["pr.barcode = ?"]
    params = [barcode]
    if not include_old:
        where.append("pr.date >= ?")
        params.append(fresh_cutoff())
    if chains:
        where.append("pr.chain IN (%s)" % ",".join("?" * len(chains)))
        params += chains
    raw_cities = city_raw_values(city) if city else None
    if raw_cities is not None:
        if not raw_cities:
            raw_cities = ["\x00none"]
        where.append("s.city IN (%s)" % ",".join("?" * len(raw_cities)))
        params += raw_cities

    rows = q(
        f"""
        SELECT pr.price, pr.chain, pr.store_id, pr.date,
               s.store_name, s.city, s.address, s.notes
        FROM prices pr LEFT JOIN stores s ON s.chain = pr.chain AND s.store_id = pr.store_id
        WHERE {' AND '.join(where)}
        ORDER BY pr.price
        """,
        params,
    )
    excluded_old = 0
    if not include_old:
        excluded_old = q1(
            "SELECT COUNT(*) n FROM prices WHERE barcode = ? AND date < ?",
            (barcode, fresh_cutoff()),
        )["n"]

    branches = []
    for r in rows:
        city_name, cnote = city_display(r["city"])
        if r["store_name"] is None and r["city"] is None:
            city_name, cnote = UNKNOWN, NOTE_NO_STORE_FILE
        notes = [n for n in [(r["notes"] or ""), cnote] if n]
        branches.append({
            "price": money(r["price"]), "chain": r["chain"], "store_id": r["store_id"],
            "branch": r["store_name"] or f"סניף {r['store_id']}",
            "city": city_name, "address": r["address"] or UNKNOWN,
            "date": r["date"], "note": "; ".join(dict.fromkeys(notes)),
        })

    prices = [b["price"] for b in branches]
    stats = None
    if prices:
        med = statistics.median(prices)
        stats = {
            "min": prices[0], "max": prices[-1], "median": money(med),
            "avg": money(sum(prices) / len(prices)),
            "gap_pct": round((prices[-1] - prices[0]) / prices[0] * 100, 1) if prices[0] else 0,
            "gap_shekel": money(prices[-1] - prices[0]),
            "count": len(prices),
            "min_branch": branches[0], "max_branch": branches[-1],
            "dates": sorted({b["date"] for b in branches}),
        }

    by_chain = {}
    for b in branches:
        by_chain.setdefault(b["chain"], []).append(b["price"])
    chain_rows = sorted(
        ({"chain": c, "avg": money(sum(v) / len(v)), "min": money(min(v)),
          "max": money(max(v)), "stores": len(v)} for c, v in by_chain.items()),
        key=lambda x: x["avg"],
    )
    for i, cr in enumerate(chain_rows):
        cr["color"] = heat_color(i, len(chain_rows))

    by_city = {}
    for b in branches:
        if b["city"] == UNKNOWN:
            continue
        by_city.setdefault(b["city"], []).append(b["price"])
    city_rows = sorted(
        ({"city": c, "min": money(min(v)), "avg": money(sum(v) / len(v)), "stores": len(v)}
         for c, v in by_city.items()),
        key=lambda x: x["min"],
    )
    for i, cr in enumerate(city_rows):
        cr["color"] = heat_color(i, len(city_rows))

    history = []
    for r in q("SELECT date, median, min_price, max_price, n_stores FROM market_daily "
               "WHERE barcode = ? ORDER BY date", (barcode,)):
        history.append({"date": r["date"], "median": money(r["median"]),
                        "min": money(r["min_price"]), "max": money(r["max_price"]),
                        "stores": r["n_stores"]})

    all_chains = [r["chain"] for r in q(
        "SELECT DISTINCT chain FROM prices WHERE barcode = ? ORDER BY chain", (barcode,))]

    return {
        "product": product_brief(row),
        "stats": stats,
        "branches": branches[:400],
        "branch_count": len(branches),
        "chain_rows": chain_rows,
        "city_rows": city_rows,
        "history": history,
        "all_chains": all_chains,
        "excluded_old": excluded_old,
        "no_city_count": sum(1 for b in branches if b["city"] == UNKNOWN),
        "meta": data_meta(),
    }


def api_market(p):
    barcode = p.get("barcode", [""])[0]
    items = []
    for r in q(
        """
        SELECT mp.barcode, mp.symbol, ps.name, ps.n_stores FROM market_products mp
        JOIN product_stats ps ON ps.barcode = mp.barcode ORDER BY mp.rank
        """
    ):
        series = q("SELECT date, median FROM market_daily WHERE barcode = ? ORDER BY date DESC LIMIT 30",
                   (r["barcode"],))
        if not series:
            continue
        last = series[0]
        prev = series[1] if len(series) > 1 else None
        items.append({
            "barcode": r["barcode"], "symbol": r["symbol"], "name": r["name"],
            "stores": r["n_stores"], "price": money(last["median"]), "date": last["date"],
            "prev": money(prev["median"]) if prev else None,
            "prev_date": prev["date"] if prev else None,
            "change": pct(last["median"], prev["median"]) if prev else None,
            "spark": [money(s["median"]) for s in series][::-1],
        })
    sel = None
    if items:
        chosen = next((i for i in items if i["barcode"] == barcode), items[0])
        sel = dict(chosen)
        full = q("SELECT date, median, min_price, max_price, n_stores FROM market_daily "
                 "WHERE barcode = ? ORDER BY date", (chosen["barcode"],))
        sel["series"] = [{"date": r["date"], "median": money(r["median"]), "min": money(r["min_price"]),
                          "max": money(r["max_price"]), "stores": r["n_stores"]} for r in full]
        row = product_row(chosen["barcode"])
        sel["today"] = product_brief(row)
        depth = []
        cutoff = fresh_cutoff()
        for r in q(
            """
            SELECT chain, AVG(price) a, MIN(price) mn, MAX(price) mx, COUNT(*) n
            FROM prices WHERE barcode = ? AND date >= ? GROUP BY chain ORDER BY a
            """,
            (chosen["barcode"], cutoff),
        ):
            depth.append({"chain": r["chain"], "avg": money(r["a"]), "min": money(r["mn"]),
                          "max": money(r["mx"]), "stores": r["n"]})
        for i, d in enumerate(depth):
            d["color"] = heat_color(i, len(depth))
        sel["depth"] = depth
    movers = [i for i in items if i["change"] is not None]
    return {
        "items": items,
        "selected": sel,
        "losers": sorted(movers, key=lambda x: x["change"])[:3],
        "gainers": sorted(movers, key=lambda x: -x["change"])[:3],
        "meta": data_meta(),
    }


def basket_analysis(entries, city=None, include_old=False):
    """
    ניתוח סל: הסניף הזול לכל הסל, והפיצול הזול ביותר.
    כל מחיר נושא את התאריך שבו הרשת פרסמה אותו.
    """
    wanted = {}
    for e in entries:
        code = str(e.get("barcode", "")).strip()
        if not code:
            continue
        wanted[code] = wanted.get(code, 0) + max(1, int(e.get("qty", 1) or 1))
    if not wanted:
        return {"error": "הסל ריק"}
    codes = list(wanted)

    where = ["pr.barcode IN (%s)" % ",".join("?" * len(codes))]
    params = list(codes)
    if not include_old:
        where.append("pr.date >= ?")
        params.append(fresh_cutoff())
    raw_cities = city_raw_values(city) if city else None
    if raw_cities is not None:
        if not raw_cities:
            raw_cities = ["\x00none"]
        where.append("s.city IN (%s)" % ",".join("?" * len(raw_cities)))
        params += raw_cities

    rows = q(
        f"""
        SELECT pr.chain, pr.store_id, pr.barcode, pr.price, pr.date,
               s.store_name, s.city, s.address, s.notes
        FROM prices pr LEFT JOIN stores s ON s.chain = pr.chain AND s.store_id = pr.store_id
        WHERE {' AND '.join(where)}
        """,
        params,
    )

    stores, info = {}, {}
    for r in rows:
        key = (r["chain"], r["store_id"])
        cur = stores.setdefault(key, {})
        prev = cur.get(r["barcode"])
        if prev is None or r["price"] < prev[0]:
            cur[r["barcode"]] = (r["price"], r["date"])
        if key not in info:
            city_name, cnote = city_display(r["city"])
            if r["store_name"] is None and r["city"] is None:
                city_name, cnote = UNKNOWN, NOTE_NO_STORE_FILE
            notes = [n for n in [(r["notes"] or ""), cnote] if n]
            info[key] = {"chain": r["chain"], "store_id": r["store_id"],
                         "branch": r["store_name"] or f"סניף {r['store_id']}",
                         "city": city_name, "address": r["address"] or UNKNOWN,
                         "note": "; ".join(dict.fromkeys(notes))}

    names = {r["barcode"]: (r["name"] or UNKNOWN)
             for r in q("SELECT barcode, name FROM product_stats WHERE barcode IN (%s)"
                        % ",".join("?" * len(codes)), codes)}
    available = [c for c in codes if any(c in sp for sp in stores.values())]
    missing = [c for c in codes if c not in available]

    def total(key, subset):
        sp = stores[key]
        return sum(sp[b][0] * wanted[b] for b in subset)

    full = [k for k, sp in stores.items() if all(b in sp for b in available)]
    ranked = sorted(full, key=lambda k: total(k, available)) if full else sorted(
        stores, key=lambda k: (-sum(1 for b in available if b in stores[k]),
                               total(k, [b for b in available if b in stores[k]])))
    best_list = []
    for k in ranked[:12]:
        have = [b for b in available if b in stores[k]]
        dates = sorted({stores[k][b][1] for b in have})
        best_list.append({**info[k], "total": money(total(k, have)), "items": len(have),
                          "complete": len(have) == len(available),
                          "dates": dates})

    per_item = {}
    for b in available:
        cands = [(sp[b][0], k) for k, sp in stores.items() if b in sp]
        price, key = min(cands)
        per_item[b] = {"price": money(price), "store": key, "date": stores[key][b][1]}
    split_total = money(sum(per_item[b]["price"] * wanted[b] for b in per_item))
    by_store = {}
    for b, v in per_item.items():
        by_store.setdefault(v["store"], []).append(
            {"barcode": b, "name": names.get(b, UNKNOWN), "price": v["price"],
             "qty": wanted[b], "date": v["date"], "tint": tint_for(b)})
    split = sorted(
        ({"store": info[k], "items": lst,
          "total": money(sum(i["price"] * i["qty"] for i in lst))} for k, lst in by_store.items()),
        key=lambda s: -s["total"],
    )

    chain_totals = {}
    for k, sp in stores.items():
        have = [b for b in available if b in sp]
        if len(have) != len(available):
            continue
        t = total(k, available)
        cur = chain_totals.get(k[0])
        if cur is None or t < cur["total"]:
            chain_totals[k[0]] = {"chain": k[0], "total": money(t), "store": info[k]}
    chain_list = sorted(chain_totals.values(), key=lambda x: x["total"])
    for i, c in enumerate(chain_list):
        c["color"] = heat_color(i, len(chain_list))

    items_out = []
    for b in codes:
        cands = sorted(((sp[b][0], k) for k, sp in stores.items() if b in sp))
        row = product_row(b)
        items_out.append({
            "barcode": b, "name": names.get(b, UNKNOWN), "qty": wanted[b], "tint": tint_for(b),
            "min": money(cands[0][0]) if cands else None,
            "max": money(cands[-1][0]) if cands else None,
            "found": bool(cands),
            "stores": len(cands),
            "national_min": money(row["min_price"]) if row else None,
            "national_max": money(row["max_price"]) if row else None,
        })

    best = best_list[0] if best_list else None
    # פירוט המחירים בסניף הזול ביותר, לקבלה שמוצגת למשתמש
    best_items = []
    if best:
        key = (best["chain"], best["store_id"])
        for b in codes:
            entry = stores.get(key, {}).get(b)
            best_items.append({
                "barcode": b, "name": names.get(b, UNKNOWN), "qty": wanted[b],
                "price": money(entry[0]) if entry else None,
                "date": entry[1] if entry else None,
                "total": money(entry[0] * wanted[b]) if entry else None,
            })
    return {
        "items": items_out,
        "missing": missing,
        "available": len(available),
        "best": best,
        "best_items": best_items,
        "best_list": best_list,
        "split": split,
        "split_total": split_total,
        "split_saving": money(best["total"] - split_total) if best else 0,
        "chain_totals": chain_list,
        "city": city or "",
        "store_count": len(stores),
        "meta": data_meta(),
    }


def api_basket(_p, body=None):
    body = body or {}
    return basket_analysis(body.get("items", []), body.get("city") or None,
                           bool(body.get("include_old")))


RECEIPT_LINE = re.compile(
    r"^\s*(?:(?P<qty>\d+(?:[.,]\d+)?)\s*[xX*×]\s*)?"
    r"(?P<body>.+?)"
    r"(?:\s+(?P<price>\d+(?:[.,]\d{1,2})?))?\s*(?:₪|ש\"ח|שח)?\s*$"
)


def parse_receipt(text):
    """
    ממיר טקסט קבלה לשורות. כל שורה: כמות, תיאור, ומחיר ששולם אם נמצא.
    לא ממציא כלום: שורה שלא זוהתה מסומנת ככזו.
    """
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or len(line) < 2:
            continue
        if re.fullmatch(r"[\d\s.,:\-*=₪]+", line):
            continue
        m = RECEIPT_LINE.match(line)
        if not m:
            out.append({"raw": line, "desc": line, "qty": 1, "paid": None})
            continue
        body = m.group("body").strip(" .-\t")
        price = m.group("price")
        qty = m.group("qty")
        barcode = None
        bm = re.search(r"\b(\d{8,14})\b", body)
        if bm:
            barcode = bm.group(1)
            body = (body[:bm.start()] + " " + body[bm.end():]).strip()
        out.append({
            "raw": line,
            "desc": body or line,
            "barcode": barcode,
            "qty": float(qty.replace(",", ".")) if qty else 1,
            "paid": float(price.replace(",", ".")) if price else None,
        })
    return out


def api_receipt(_p, body=None):
    body = body or {}
    lines = parse_receipt(body.get("text", ""))
    city = body.get("city") or None
    matched, unmatched = [], []
    for ln in lines:
        prod = None
        if ln.get("barcode"):
            r = product_row(ln["barcode"])
            if r:
                prod = product_brief(r)
        if prod is None:
            hits = search_products(ln["desc"], limit=3)
            if hits:
                prod = hits[0]
                ln["ambiguous"] = [h["name"] for h in hits[1:]]
        if prod:
            matched.append({**ln, "product": prod})
        else:
            unmatched.append(ln)
    analysis = None
    if matched:
        analysis = basket_analysis(
            [{"barcode": m["product"]["barcode"], "qty": int(m["qty"]) or 1} for m in matched], city)
        cheapest = {}
        if analysis.get("best"):
            key = (analysis["best"]["chain"], analysis["best"]["store_id"])
            for s in analysis["split"]:
                for it in s["items"]:
                    cheapest[it["barcode"]] = it
            best_store_prices = {}
            for m in matched:
                code = m["product"]["barcode"]
                r = q1(
                    "SELECT price, date FROM prices WHERE chain=? AND store_id=? AND barcode=?",
                    (key[0], key[1], code))
                if r:
                    best_store_prices[code] = {"price": money(r["price"]), "date": r["date"]}
            analysis["best_store_prices"] = best_store_prices
        analysis["cheapest_by_item"] = cheapest
    paid_total = sum((m["paid"] or 0) * m["qty"] for m in matched if m["paid"] is not None)
    return {
        "matched": matched, "unmatched": unmatched,
        "paid_total": money(paid_total) if paid_total else None,
        "paid_known": sum(1 for m in matched if m["paid"] is not None),
        "analysis": analysis,
        "meta": data_meta(),
    }


ROUTES_GET = {
    "/api/meta": api_meta,
    "/api/home": api_home,
    "/api/search": api_search,
    "/api/suggest": api_search,
    "/api/product": api_product,
    "/api/market": api_market,
}
ROUTES_POST = {
    "/api/basket": api_basket,
    "/api/receipt": api_receipt,
}


# ------------------------------------------------------------------ http
class Handler(BaseHTTPRequestHandler):
    server_version = "Mehiron"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # שקט; שגיאות מודפסות בנפרד

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _json(self, data, code=200):
        self._send(code, json.dumps(data, ensure_ascii=False))

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in ROUTES_GET:
            try:
                self._json(ROUTES_GET[path](parse_qs(parsed.query)))
            except Exception as exc:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                self._json({"error": str(exc)}, 500)
            return
        self._static(path)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        fn = ROUTES_POST.get(path)
        if not fn:
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            self._json(fn(parse_qs(parsed.query), body))
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self._json({"error": str(exc)}, 500)

    def _static(self, path):
        if path == "/config.js":
            self._send(200, LOCAL_CONFIG, "application/javascript; charset=utf-8")
            return
        if path in ("/", ""):
            path = "/index.html"
        target = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not target.startswith(STATIC_DIR) or not os.path.isfile(target):
            target = os.path.join(STATIC_DIR, "index.html")   # ניווט בצד הלקוח
            if not os.path.isfile(target):
                self._send(404, "not found", "text/plain; charset=utf-8")
                return
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(target, "rb") as fh:
            self._send(200, fh.read(), ctype)


def check_ready():
    """מוודא שהמסד והאינדקס קיימים לפני שמפעילים את השרת."""
    if not os.path.exists(DB_PATH):
        print(f"לא נמצא קובץ הנתונים:\n  {DB_PATH}\nהריצו קודם: il-prices update")
        return False
    try:
        n = q1("SELECT COUNT(*) n FROM product_stats")["n"]
        q1("SELECT COUNT(*) n FROM chain_stats")
    except sqlite3.OperationalError:
        print("האינדקס של האפליקציה חסר. הריצו: python app\\build_index.py")
        return False
    if not n:
        print("האינדקס ריק. הריצו: python app\\build_index.py")
        return False
    return True


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="שרת האפליקציה מחירון")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 כדי לאפשר גישה ממכשירים אחרים ברשת המקומית")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if not check_ready():
        return 1
    m = data_meta()
    print("=" * 58)
    print("  מחירון - השוואת מחירי סופרמרקט")
    print("=" * 58)
    print(f"  נתונים: {m['price_rows']:,} מחירים · {m['stores_total']:,} סניפים · "
          f"{len(m['chains'])} רשתות · עדכון אחרון {m['latest_date']}")
    url = f"http://{'localhost' if args.host == '127.0.0.1' else args.host}:{args.port}/"
    print(f"  כתובת: {url}")
    if args.host == "0.0.0.0":
        print("  (פתוח לכל המכשירים ברשת המקומית)")
    print("  לעצירה: Ctrl+C")
    print("=" * 58)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nהשרת נעצר.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
