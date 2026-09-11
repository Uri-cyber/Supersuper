# -*- coding: utf-8 -*-
"""
בונה טבלאות עזר מתוך prices.db כדי שהאפליקציה תגיב מיד.

הטבלאות נגזרות במלואן מהנתונים שהרשתות פרסמו - שום ערך לא מנוחש.
מריצים: python build_index.py   (או דרך מחירון.bat, שמריץ את זה לבד כשצריך)
"""
import datetime as dt
import os
import sqlite3
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(os.path.dirname(BASE_DIR), "prices.db")

# גרסת האינדקס - שינוי כאן מאלץ בנייה מחדש
INDEX_VERSION = "8"

# חלון הטריות: השוואות נעשות רק בין מחירים מאותו חלון זמן
FRESH_DAYS = 7

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS product_stats (
    barcode     TEXT PRIMARY KEY,
    name        TEXT,
    n_stores    INTEGER NOT NULL,
    n_chains    INTEGER NOT NULL,
    min_price   REAL NOT NULL,
    max_price   REAL NOT NULL,
    median      REAL NOT NULL,
    avg_price   REAL NOT NULL,
    gap_pct     REAL NOT NULL,
    min_chain   TEXT, min_store INTEGER, min_date TEXT,
    max_chain   TEXT, max_store INTEGER, max_date TEXT,
    fresh       INTEGER NOT NULL DEFAULT 1,   -- 1 = מחושב ממחירים בחלון הטריות
    date_min    TEXT, date_max TEXT           -- טווח התאריכים שהשוואה זו מבוססת עליו
);
CREATE INDEX IF NOT EXISTS idx_ps_stores ON product_stats(n_stores DESC);
CREATE INDEX IF NOT EXISTS idx_ps_gap ON product_stats(gap_pct DESC);

CREATE TABLE IF NOT EXISTS market_daily (
    barcode  TEXT NOT NULL,
    date     TEXT NOT NULL,
    n_stores INTEGER NOT NULL,
    min_price REAL NOT NULL,
    max_price REAL NOT NULL,
    median   REAL NOT NULL,
    avg_price REAL NOT NULL,
    PRIMARY KEY (barcode, date)
);

CREATE TABLE IF NOT EXISTS chain_stats (
    chain     TEXT PRIMARY KEY,
    stores    INTEGER NOT NULL,
    rows      INTEGER NOT NULL,
    date_min  TEXT,
    date_max  TEXT,
    has_store_file INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS city_stats (
    city   TEXT PRIMARY KEY,
    stores INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS market_products (
    barcode TEXT PRIMARY KEY,
    symbol  TEXT,
    rank    INTEGER
);

CREATE TABLE IF NOT EXISTS ticker (
    barcode    TEXT PRIMARY KEY,
    name       TEXT,
    price      REAL,
    prev_price REAL,
    change     REAL,
    date       TEXT,
    prev_date  TEXT,
    stores     INTEGER
);
"""

# ---------------------------------------------------------------- הבאנר הרץ
# מחושב כאן פעם ביום ולא בדפדפן: השאילתה עוברת על כל market_daily, וזה
# לא משהו שרוצים לעשות דרך HTTP-Range מול קובץ של 2 ג'יגה.
#
# 1. רק מוצרים שנמכרים בהרבה סניפים. סף של 300 סניפים (כ-13% מהסניפים
#    בארץ) נבחר לפי מדידה מ-11.09.2026: 293 מועמדים שעברו את כל המסננים
#    באותו יום, בהשוואה ל-1,351 בסף 30 - כלומר יש מספיק, וכל מה שמוצג הוא
#    מוצר שהקורא מכיר מהמדף ולא פריט נישה שמדווח עליו חצי סניף.
# 2. שתי הנקודות מבוססות על כיסוי דומה. אם היום דיווחו 400 סניפים ואתמול
#    150, ההפרש בחציון משקף מי דיווח ולא שינוי מחיר.
# 3. הנקודה הקודמת קרובה בזמן. שינוי מול לפני חצי שנה אינו "תנועת היום".
# 4. פיזור המחירים באותו יום קטן. אותו ברקוד נושא לפעמים מחירים ביחידות
#    שונות (ל-100 גרם מול לקילו), ואז החציון קופץ בלי שמחיר השתנה.
TICKER_LIMIT = 14
TICKER_MIN_STORES = 300
TICKER_MAX_COVERAGE_RATIO = 2.0
TICKER_MAX_GAP_DAYS = 30
TICKER_MAX_SPREAD = 5.0


def build_ticker(conn):
    log("בונה את הבאנר הרץ...")
    conn.execute("DELETE FROM ticker")
    rows = conn.execute(
        """
        WITH ranked AS (
          SELECT barcode, date, median, n_stores, min_price, max_price,
                 ROW_NUMBER() OVER (PARTITION BY barcode ORDER BY date DESC) rn
          FROM market_daily
        )
        SELECT a.barcode, a.date, a.median, a.n_stores,
               a.min_price AS lo, a.max_price AS hi,
               b.date AS prev_date, b.median AS prev_median, b.n_stores AS prev_stores,
               b.min_price AS prev_lo, b.max_price AS prev_hi,
               ps.name
        FROM ranked a
        JOIN ranked b ON b.barcode = a.barcode AND b.rn = 2
        JOIN product_stats ps ON ps.barcode = a.barcode
        WHERE a.rn = 1
          AND a.date = (SELECT MAX(date) FROM market_daily)
          AND a.n_stores >= ? AND b.n_stores >= ?
          AND ps.name IS NOT NULL AND ps.name <> ''
        """,
        (TICKER_MIN_STORES, TICKER_MIN_STORES),
    ).fetchall()

    out = []
    for (bc, date, med, n, lo, hi, pdate, pmed, pn, plo, phi, name) in rows:
        if min(n, pn) and max(n, pn) / min(n, pn) > TICKER_MAX_COVERAGE_RATIO:
            continue
        spread = 0
        for a, b in ((lo, hi), (plo, phi)):
            if a and a > 0:
                spread = max(spread, b / a)
        if spread > TICKER_MAX_SPREAD:
            continue
        try:
            gap = (dt.date.fromisoformat(date) - dt.date.fromisoformat(pdate)).days
        except ValueError:
            continue
        if gap > TICKER_MAX_GAP_DAYS or not pmed:
            continue
        chg = round((med - pmed) / pmed * 100, 1)
        if chg == 0:
            continue
        out.append((bc, name, round(med, 2), round(pmed, 2), chg, date, pdate, n))

    # החדים ביותר, ובכוונה משני הכיוונים: באנר שמראה רק התייקרויות מספר
    # סיפור אחד ולא את מה שקרה באמת.
    ups = sorted((x for x in out if x[4] > 0), key=lambda x: -x[4])
    downs = sorted((x for x in out if x[4] < 0), key=lambda x: x[4])
    half = TICKER_LIMIT // 2
    picked = ups[:half] + downs[:TICKER_LIMIT - half]
    if len(picked) < TICKER_LIMIT:
        rest = [x for x in out if x not in picked]
        rest.sort(key=lambda x: -abs(x[4]))
        picked += rest[:TICKER_LIMIT - len(picked)]
    conn.executemany("INSERT OR REPLACE INTO ticker VALUES (?,?,?,?,?,?,?,?)", picked)
    conn.commit()
    log(f"    {len(out):,} מועמדים עברו את המסננים, נבחרו {len(picked)}")



def log(msg):
    print(msg, flush=True)


def median_of(sorted_vals):
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2


def build_product_stats(conn):
    """
    סטטיסטיקה לכל ברקוד: מינימום, מקסימום, חציון, ומי הסניף בכל קצה.

    ההשוואה נעשית רק בין מחירים מחלון הטריות (7 ימים אחרונים שיש בהם נתונים),
    כדי שלא יושווה מחיר של היום מול מחיר בן חודשיים מסניף שהרשת הפסיקה לפרסם.
    למוצר שכל מחיריו ישנים יותר נשמרת השוואה על כל מה שיש, עם סימון fresh=0.
    """
    latest = conn.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    cutoff = (dt.date.fromisoformat(latest) - dt.timedelta(days=FRESH_DAYS)).isoformat()
    log(f"בונה סטטיסטיקת מוצרים (השוואה על מחירים מ-{cutoff} ואילך)...")
    t0 = time.time()
    conn.execute("DELETE FROM product_stats")
    names = dict(conn.execute("SELECT barcode, name FROM products"))

    cur = conn.execute(
        "SELECT barcode, price, chain, store_id, date FROM prices ORDER BY barcode"
    )
    batch, total, stale = [], 0, 0
    cur_code, rows = None, []

    def flush_group(code, group):
        nonlocal stale
        fresh_rows = [r for r in group if r[3] >= cutoff]
        is_fresh = 1
        if not fresh_rows:
            fresh_rows = group
            is_fresh = 0
            stale += 1
        prices = sorted(r[0] for r in fresh_rows)
        lo = min(fresh_rows, key=lambda r: r[0])
        hi = max(fresh_rows, key=lambda r: r[0])
        dates = [r[3] for r in fresh_rows]
        gap = ((hi[0] - lo[0]) / lo[0] * 100) if lo[0] > 0 else 0.0
        batch.append((
            code, names.get(code), len(fresh_rows), len({r[1] for r in fresh_rows}),
            lo[0], hi[0], median_of(prices), sum(prices) / len(prices), gap,
            lo[1], lo[2], lo[3], hi[1], hi[2], hi[3],
            is_fresh, min(dates), max(dates),
        ))

    def flush_batch():
        nonlocal batch, total
        if batch:
            conn.executemany(
                "INSERT OR REPLACE INTO product_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                batch)
            total += len(batch)
            batch = []

    for barcode, price, chain, store_id, date in cur:
        if barcode != cur_code:
            if cur_code is not None:
                flush_group(cur_code, rows)
            cur_code, rows = barcode, []
        rows.append((price, chain, store_id, date))
        if len(batch) >= 5000:
            flush_batch()
    if cur_code is not None:
        flush_group(cur_code, rows)
    flush_batch()
    conn.commit()
    log(f"  {total:,} מוצרים ({stale:,} ללא מחיר עדכני), {round(time.time() - t0)} שניות")
    return total


# סמלים קצרים למסך הבורסה, נגזרים מהברקוד (יציב, לא מומצא)
def symbol_for(barcode, taken):
    digits = "".join(ch for ch in barcode if ch.isdigit()) or barcode
    base = digits[-4:].rjust(4, "0")
    sym = base
    i = 1
    while sym in taken:
        sym = base[:3] + str(i % 10)
        i += 1
        if i > 50:
            sym = digits[-5:-1].rjust(4, "0")
            break
    taken.add(sym)
    return sym


def build_market(conn, tracked_limit=120):
    """
    סדרה יומית ארצית לכל מוצר שיש לו היסטוריה.

    price_history שומרת רק שינויים, ולכן משחזרים לכל יום את המצב המלא:
    מחזיקים מיפוי סניף->מחיר, מעדכנים אותו לפי סדר התאריכים, ומצלמים בסוף
    כל יום. מחיר NULL פירושו שהמוצר הפסיק להימכר באותו סניף, והוא יוצא
    מהחישוב.

    נשמרת שורה רק ליום שבו משהו השתנה. יום ללא שינוי אינו מייצר שורה, וזה
    לא חוסר: המחיר פשוט נשאר מה שהיה, והתצוגה גוררת אותו קדימה. אחסון של
    שורה לכל מוצר ולכל יום היה מוסיף כ-33 מיליון שורות בשנה במקום כ-1.3
    מיליון, בלי להוסיף שום מידע.

    סריקה אחת מסודרת לפי (מוצר, תאריך) על פני כל הטבלה. הגרסה הקודמת הריצה
    שאילתה נפרדת לכל מוצר, מה שהגביל אותה ל-5,000 המוצרים הנפוצים; נמדד
    שסריקה אחת עוברת 17 מיליון שורות ב-40 שניות ומכסה את כולם.

    tracked_limit - כמה מוצרים מופיעים ברשימת הבורסה ובטיקר
    """
    log("בונה סדרות יומיות לכל המוצרים...")
    t0 = time.time()
    conn.execute("DELETE FROM market_daily")
    conn.execute("DELETE FROM market_products")

    def flush(buf):
        if buf:
            conn.executemany("INSERT OR REPLACE INTO market_daily VALUES (?,?,?,?,?,?,?)", buf)

    rows_out = []
    total = prods = 0
    cur_bc = cur_date = None
    state = {}

    def snapshot():
        """סוגר את היום הפתוח ומוסיף לו שורה, אם דיווח עליו לפחות סניף אחד."""
        if cur_bc is None or cur_date is None:
            return 0
        vals = sorted(state.values())
        if not vals:
            return 0
        rows_out.append((cur_bc, cur_date, len(vals), vals[0], vals[-1],
                         median_of(vals), sum(vals) / len(vals)))
        return 1

    for bc, date, chain, store_id, price in conn.execute(
        "SELECT barcode, date, chain, store_id, price FROM price_history "
        "ORDER BY barcode, date"
    ):
        if bc != cur_bc:
            total += snapshot()
            state = {}
            cur_bc, cur_date = bc, None
            prods += 1
            if prods % 25000 == 0:
                log(f"    {prods:,} מוצרים, {total:,} נקודות, {round(time.time() - t0)} שניות")
                flush(rows_out)
                rows_out = []
        elif date != cur_date:
            total += snapshot()
        cur_date = date
        key = (chain, store_id)
        if price is None:
            state.pop(key, None)
        else:
            state[key] = price
    total += snapshot()
    flush(rows_out)
    conn.commit()

    # רשימת הבורסה: הנפוצים ביותר, ורק כאלה שבאמת יש להם סדרה להציג
    taken = set()
    prods_out, rank = [], 0
    for (barcode,) in conn.execute(
        """
        SELECT ps.barcode FROM product_stats ps
        WHERE ps.name IS NOT NULL AND ps.name <> '' AND ps.n_stores >= 50
        ORDER BY ps.n_stores DESC, ps.gap_pct DESC
        """
    ):
        if conn.execute("SELECT 1 FROM market_daily WHERE barcode=? LIMIT 1",
                        (barcode,)).fetchone() is None:
            continue
        rank += 1
        prods_out.append((barcode, symbol_for(barcode, taken), rank))
        if rank >= tracked_limit:
            break
    conn.executemany("INSERT OR REPLACE INTO market_products VALUES (?,?,?)", prods_out)
    conn.commit()

    n = conn.execute("SELECT COUNT(*) FROM market_daily").fetchone()[0]
    m = conn.execute("SELECT COUNT(DISTINCT barcode) FROM market_daily").fetchone()[0]
    log(f"  {m:,} מוצרים עם גרף, {len(prods_out)} בבורסה, {n:,} נקודות, "
        f"{round(time.time() - t0)} שניות")


def build_chain_stats(conn):
    """סיכום לכל רשת: סניפים, רשומות וטווח תאריכים. נשמר כדי שהאפליקציה תיפתח מיד."""
    log("מסכם רשתות...")
    t0 = time.time()
    conn.execute("DELETE FROM chain_stats")
    with_store_file = {r[0] for r in conn.execute("SELECT DISTINCT chain FROM stores")}
    rows = conn.execute(
        """
        SELECT chain, COUNT(DISTINCT store_id), COUNT(*), MIN(date), MAX(date)
        FROM prices GROUP BY chain
        """
    ).fetchall()
    conn.executemany(
        "INSERT OR REPLACE INTO chain_stats VALUES (?,?,?,?,?,?)",
        [(c, st, n, d1, d2, 1 if c in with_store_file else 0) for c, st, n, d1, d2 in rows],
    )
    latest = conn.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    today_stores = conn.execute(
        "SELECT COUNT(*) FROM (SELECT chain, store_id FROM prices WHERE date = ? GROUP BY chain, store_id)",
        (latest,),
    ).fetchone()[0]
    total_stores = conn.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT chain, store_id FROM prices)"
    ).fetchone()[0]
    for key, val in [("latest_date", latest), ("stores_today", today_stores),
                     ("stores_total", total_stores),
                     ("price_rows", conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0])]:
        conn.execute("INSERT OR REPLACE INTO app_meta VALUES (?, ?)", (key, str(val)))
    conn.execute("DELETE FROM city_stats")
    conn.executemany(
        "INSERT OR REPLACE INTO city_stats VALUES (?,?)",
        conn.execute("SELECT city, COUNT(*) FROM stores GROUP BY city").fetchall(),
    )
    conn.commit()
    log(f"  {len(rows)} רשתות, {round(time.time() - t0)} שניות")


def build_search_index(conn):
    """אינדקס חיפוש מהיר על שמות מוצרים (FTS5), עם נפילה חזרה ל-LIKE אם אינו זמין."""
    log("בונה אינדקס חיפוש...")
    t0 = time.time()
    try:
        conn.execute("DROP TABLE IF EXISTS product_fts")
        conn.execute(
            "CREATE VIRTUAL TABLE product_fts USING fts5(name, barcode UNINDEXED, tokenize='unicode61')"
        )
        conn.execute(
            """
            INSERT INTO product_fts(name, barcode)
            SELECT ps.name, ps.barcode FROM product_stats ps
            WHERE ps.name IS NOT NULL AND ps.name <> ''
            """
        )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM product_fts").fetchone()[0]
        log(f"  {n:,} שמות, {round(time.time() - t0)} שניות")
        return True
    except sqlite3.OperationalError as exc:
        log(f"  FTS5 לא זמין ({exc}) - החיפוש יעבוד בשיטה איטית יותר")
        return False


def needs_build(conn):
    """
    האם צריך לבנות את האינדקס מחדש.

    לא מספיק להשוות את מספר השורות ב-prices. המפתח שם הוא
    (chain, store_id, barcode) והקליטה כותבת ב-ON CONFLICT DO UPDATE, ולכן
    ביום שבו אותם סניפים פרסמו את אותו קטלוג מספר השורות זהה בדיוק בזמן
    שכל המחירים השתנו. בדיקה על המספר בלבד הייתה מדלגת על הבנייה, והאתר
    היה מקבל מחירים של היום עם סיכומים של אתמול.

    לכן נבדק גם התאריך האחרון שבנתונים מול מה שהאינדקס בנוי עליו.
    """
    try:
        row = conn.execute("SELECT value FROM app_meta WHERE key = 'index_version'").fetchone()
    except sqlite3.OperationalError:
        return True
    if not row or row[0] != INDEX_VERSION:
        return True

    row = conn.execute("SELECT value FROM app_meta WHERE key = 'index_prices_rows'").fetchone()
    current = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    if not row or row[0] != str(current):
        return True

    # התאריך האחרון בנתונים עצמם, מול זה שהאינדקס נבנה לפיו
    newest = conn.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    row = conn.execute("SELECT value FROM app_meta WHERE key = 'index_latest_date'").fetchone()
    if newest is not None and (not row or row[0] != str(newest)):
        return True

    return False


def main(force=False):
    if not os.path.exists(DB_PATH):
        log(f"לא נמצא קובץ הנתונים {DB_PATH}. הריצו קודם: il-prices update")
        return 1
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    if not force and not needs_build(conn):
        log("האינדקס מעודכן.")
        return 0
    # מבנה הטבלאות משתנה בין גרסאות אינדקס - בונים אותן מאפס
    for tbl in ("product_stats", "market_daily", "market_products", "chain_stats", "city_stats", "ticker"):
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")
    conn.execute("DROP TABLE IF EXISTS product_fts")
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-200000")
    build_product_stats(conn)
    build_chain_stats(conn)
    build_search_index(conn)
    build_market(conn)
    build_ticker(conn)
    conn.execute("INSERT OR REPLACE INTO app_meta VALUES ('index_version', ?)", (INDEX_VERSION,))
    conn.execute(
        "INSERT OR REPLACE INTO app_meta VALUES ('index_prices_rows', ?)",
        (str(conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO app_meta VALUES ('index_built_at', ?)",
        (time.strftime("%Y-%m-%d %H:%M"),),
    )
    newest = conn.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    conn.execute(
        "INSERT OR REPLACE INTO app_meta VALUES ('index_latest_date', ?)",
        (str(newest) if newest is not None else "",),
    )
    conn.commit()
    log("האינדקס נבנה בהצלחה.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main(force="--force" in sys.argv))
