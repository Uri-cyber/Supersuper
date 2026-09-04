# -*- coding: utf-8 -*-
"""
בונה מסד קריאה-בלבד להגשה מהענן.

מייצא מ-prices.db רק את מה שהאפליקציה קוראת. טבלת price_history, שהיא רוב
המשקל, לא נכללת - היא נחוצה רק לחישוב הסדרות היומיות, וזה כבר מוכן ב-market_daily.

VACUUM בסוף חשוב במיוחד: הוא מסדר את הדפים ברצף, וכשהדפדפן קורא את הקובץ
בחתיכות דרך HTTP Range, נתונים שכנים פירושם פחות בקשות ופחות בתים.

הרצה:  python build_cloud_db.py [--page-size 1024|4096] [--all-prices]
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DB = os.path.join(os.path.dirname(BASE_DIR), "prices.db")

# הטבלאות שהאפליקציה באמת קוראת
TABLES = ["stores", "product_stats", "market_daily", "market_products",
          "chain_stats", "city_stats", "app_meta"]

FRESH_DAYS = 7


def log(msg):
    print(msg, flush=True)


def human(n):
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def build(page_size, out_path, all_prices=False):
    if os.path.exists(out_path):
        os.remove(out_path)
    for suffix in ("-wal", "-shm"):
        if os.path.exists(out_path + suffix):
            os.remove(out_path + suffix)

    t0 = time.time()
    conn = sqlite3.connect(out_path)
    # page_size חייב להיקבע לפני שנכתב משהו למסד
    conn.execute(f"PRAGMA page_size={page_size}")
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-400000")
    conn.execute("ATTACH DATABASE ? AS src", (SRC_DB,))

    for tbl in TABLES:
        conn.execute(f"CREATE TABLE {tbl} AS SELECT * FROM src.{tbl}")
        log(f"  {tbl}: {conn.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]:,} שורות")

    latest = conn.execute("SELECT value FROM app_meta WHERE key='latest_date'").fetchone()
    latest = latest[0] if latest else dt.date.today().isoformat()
    if all_prices:
        conn.execute("CREATE TABLE prices AS SELECT * FROM src.prices")
        note = "כל המחירים"
    else:
        cutoff = (dt.date.fromisoformat(latest) - dt.timedelta(days=FRESH_DAYS)).isoformat()
        # ORDER BY barcode: שורות של אותו מוצר יישבו ברצף על הדיסק,
        # כך ששאילתת מוצר אחד נוגעת במעט דפים
        conn.execute(
            "CREATE TABLE prices AS SELECT * FROM src.prices WHERE date >= ? ORDER BY barcode, price",
            (cutoff,),
        )
        note = f"מחירים מ-{cutoff} ואילך"
    n_prices = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    log(f"  prices: {n_prices:,} שורות ({note})")

    log("  בונה אינדקסים...")
    conn.execute("CREATE INDEX idx_prices_barcode ON prices(barcode)")
    conn.execute("CREATE UNIQUE INDEX idx_ps_barcode ON product_stats(barcode)")
    conn.execute("CREATE INDEX idx_ps_stores ON product_stats(n_stores DESC)")
    conn.execute("CREATE UNIQUE INDEX idx_stores_key ON stores(chain, store_id)")
    conn.execute("CREATE INDEX idx_stores_city ON stores(city)")
    conn.execute("CREATE INDEX idx_md_barcode ON market_daily(barcode, date)")

    log("  בונה אינדקס חיפוש...")
    # השדות הנוספים שמורים באינדקס עצמו (UNINDEXED), כך שתוצאת חיפוש
    # לא דורשת צירוף לטבלת המוצרים ואינה גוררת גישות אקראיות לדיסק
    conn.execute(
        "CREATE VIRTUAL TABLE product_fts USING fts5("
        "name, barcode UNINDEXED, min_price UNINDEXED, max_price UNINDEXED, "
        "median UNINDEXED, gap_pct UNINDEXED, n_stores UNINDEXED, n_chains UNINDEXED, "
        "min_chain UNINDEXED, max_chain UNINDEXED, min_date UNINDEXED, max_date UNINDEXED, "
        # אינדקס קידומות: החיפוש באתר מוסיף * לכל מילה, ובלי זה כל תו נוסף
        # שהמשתמש מקליד סורק מחדש חלק גדול מהאינדקס
        "tokenize='unicode61', prefix='2 3 4')"
    )
    conn.execute(
        "INSERT INTO product_fts(name, barcode, min_price, max_price, median, gap_pct, "
        "n_stores, n_chains, min_chain, max_chain, min_date, max_date) "
        "SELECT name, barcode, min_price, max_price, median, gap_pct, n_stores, n_chains, "
        "min_chain, max_chain, min_date, max_date FROM product_stats "
        "WHERE name IS NOT NULL AND name <> '' ORDER BY n_stores DESC"
    )
    conn.commit()

    precompute(conn, out_path)

    log("  VACUUM...")
    conn.execute("VACUUM")
    conn.execute("PRAGMA optimize")
    conn.close()

    size = os.path.getsize(out_path)
    log(f"  → {os.path.basename(out_path)}: {human(size)} "
        f"({size // page_size:,} דפים של {page_size} בתים) ב-{time.time() - t0:.0f} שניות")
    return size


def precompute(conn, out_path):
    """
    מכין מראש את מה שזהה לכל המשתמשים: מסך הבית, רשימת הבורסה, הערים והמטא.

    בלי זה, כל מבקר היה מריץ שאילתות שסורקות אלפי דפים מהקובץ, וזה ארוך ויקר.
    התוצאה מחושבת כאן על ידי אותו קוד של השרת המקומי, כדי שהמספרים יהיו זהים.
    """
    log("  מחשב מראש את מסך הבית והבורסה...")
    t0 = time.time()
    conn.execute("CREATE TABLE IF NOT EXISTS precomputed (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()

    sys.path.insert(0, os.path.join(os.path.dirname(BASE_DIR), "app"))
    import importlib
    import server as srv
    importlib.reload(srv)
    srv.DB_PATH = os.path.abspath(out_path)
    srv._meta_cache.update(at=0, data=None)
    srv._cities_cache.update(at=0, data=None)
    srv._latest_cache.update(at=0, date=None)
    if hasattr(srv._local, "conn"):
        del srv._local.conn

    stores = [
        {"chain": r["chain"], "store_id": r["store_id"], "store_name": r["store_name"],
         "city": r["city"], "address": r["address"], "notes": r["notes"]}
        for r in srv.q("SELECT chain, store_id, store_name, city, address, notes FROM stores")
    ]
    payload = {
        "meta": srv.data_meta(),
        "cities": srv.city_list(),
        "home": srv.api_home({}),
        "market": srv.api_market({}),
        "stores": stores,
    }
    # מסך הבית והבורסה כוללים את המטא; מסירים כדי לא לשמור אותו פעמיים
    payload["home"].pop("meta", None)
    payload["market"].pop("meta", None)

    rows = [(k, json.dumps(v, ensure_ascii=False, separators=(",", ":"))) for k, v in payload.items()]
    conn.executemany("INSERT OR REPLACE INTO precomputed VALUES (?,?)", rows)
    conn.commit()
    if hasattr(srv._local, "conn"):
        srv._local.conn.close()
        del srv._local.conn
    total = sum(len(v) for _k, v in rows)
    log(f"    {len(rows)} רשומות, {total / 1024:.0f}KB, {time.time() - t0:.0f} שניות")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page-size", type=int, default=0,
                    help="גודל דף. ברירת מחדל: בונה גם 1024 וגם 4096 להשוואה")
    ap.add_argument("--all-prices", action="store_true",
                    help="לכלול גם מחירים ישנים מחלון הטריות")
    args = ap.parse_args()

    if not os.path.exists(SRC_DB):
        log(f"לא נמצא {SRC_DB}. הריצו קודם: il-prices update")
        return 1

    log(f"מקור: {SRC_DB} ({human(os.path.getsize(SRC_DB))})")
    sizes = [args.page_size] if args.page_size else [4096, 1024]
    for ps in sizes:
        log(f"\nבונה מסד עם דף {ps} בתים:")
        build(ps, os.path.join(BASE_DIR, f"mehiron-{ps}.db"), args.all_prices)
    log("\nסיום.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
