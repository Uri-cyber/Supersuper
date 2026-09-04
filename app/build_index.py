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
INDEX_VERSION = "5"

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
"""


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


def build_market(conn, limit=120):
    """
    סדרה יומית ארצית למוצרים הנפוצים ביותר.

    price_history שומרת רק שינויים, לכן משחזרים לכל יום את המצב המלא:
    מחזיקים מיפוי סניף->מחיר ומעדכנים אותו לפי סדר התאריכים.
    מחיר NULL בהיסטוריה = המוצר הפסיק להימכר באותו סניף, ולכן הוא יוצא מהחישוב.
    """
    log(f"בונה סדרות יומיות ל-{limit} המוצרים הנפוצים ביותר...")
    t0 = time.time()
    conn.execute("DELETE FROM market_daily")
    conn.execute("DELETE FROM market_products")

    top = conn.execute(
        """
        SELECT ps.barcode FROM product_stats ps
        WHERE ps.name IS NOT NULL AND ps.name <> '' AND ps.n_stores >= 200
        ORDER BY ps.n_stores DESC, ps.gap_pct DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()

    taken = set()
    rows_out, prods = [], []
    for rank, (barcode,) in enumerate(top, 1):
        state = {}
        days = {}
        for chain, store_id, price, date in conn.execute(
            "SELECT chain, store_id, price, date FROM price_history WHERE barcode = ? ORDER BY date",
            (barcode,),
        ):
            key = (chain, store_id)
            if price is None:
                state.pop(key, None)
            else:
                state[key] = price
            days[date] = None
        # מריצים שוב לפי סדר התאריכים ומצלמים מצב בסוף כל יום
        state = {}
        for date in sorted(days):
            for chain, store_id, price in conn.execute(
                "SELECT chain, store_id, price FROM price_history WHERE barcode = ? AND date = ?",
                (barcode, date),
            ):
                key = (chain, store_id)
                if price is None:
                    state.pop(key, None)
                else:
                    state[key] = price
            vals = sorted(state.values())
            if not vals:
                continue
            rows_out.append((barcode, date, len(vals), vals[0], vals[-1],
                             median_of(vals), sum(vals) / len(vals)))
        prods.append((barcode, symbol_for(barcode, taken), rank))
        if len(rows_out) > 20000:
            conn.executemany("INSERT OR REPLACE INTO market_daily VALUES (?,?,?,?,?,?,?)", rows_out)
            rows_out = []
    if rows_out:
        conn.executemany("INSERT OR REPLACE INTO market_daily VALUES (?,?,?,?,?,?,?)", rows_out)
    conn.executemany("INSERT OR REPLACE INTO market_products VALUES (?,?,?)", prods)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM market_daily").fetchone()[0]
    log(f"  {len(prods)} מוצרים, {n:,} נקודות יומיות, {round(time.time() - t0)} שניות")


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
    try:
        row = conn.execute("SELECT value FROM app_meta WHERE key = 'index_version'").fetchone()
    except sqlite3.OperationalError:
        return True
    if not row or row[0] != INDEX_VERSION:
        return True
    row = conn.execute("SELECT value FROM app_meta WHERE key = 'index_prices_rows'").fetchone()
    current = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    return not row or row[0] != str(current)


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
    for tbl in ("product_stats", "market_daily", "market_products", "chain_stats", "city_stats"):
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")
    conn.execute("DROP TABLE IF EXISTS product_fts")
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-200000")
    build_product_stats(conn)
    build_chain_stats(conn)
    build_search_index(conn)
    build_market(conn)
    conn.execute("INSERT OR REPLACE INTO app_meta VALUES ('index_version', ?)", (INDEX_VERSION,))
    conn.execute(
        "INSERT OR REPLACE INTO app_meta VALUES ('index_prices_rows', ?)",
        (str(conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO app_meta VALUES ('index_built_at', ?)",
        (time.strftime("%Y-%m-%d %H:%M"),),
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
