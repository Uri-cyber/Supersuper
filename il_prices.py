# -*- coding: utf-8 -*-
"""
il-prices: השוואת מחירי סופרמרקט בישראל ברמת סניף.

פקודות:
    update                          הורדה ועדכון יומי של כל הרשתות
    search "שם מוצר"                חיפוש ברקודים לפי שם
    price BARCODE [--city עיר]      כל הסניפים מהזול ליקר
    history BARCODE [--city עיר]    שינויי מחיר לאורך זמן (נתוני עבר)
    basket basket.txt [--city עיר]  הסניף הזול ביותר לסל ופיצול אופטימלי
    stats                           מצב מסד הנתונים
"""
import argparse
import datetime as dt
import gzip
import io
import itertools
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "prices.db")
DUMPS_DIR = os.path.join(BASE_DIR, "dumps")
STATUS_DIR = os.path.join(DUMPS_DIR, "status")
CITIES_PATH = os.path.join(BASE_DIR, "cities.json")

# שם עברי לכל רשת, לפי שם תיקיית ההורדה של החבילה il-supermarket-scraper
CHAIN_NAMES = {
    "Bareket": "ברקת",
    "YaynotBitanAndCarrefour": "יינות ביתן / קרפור",
    "CityMarketKiryatGat": "סיטי מרקט קרית גת",
    "CityMarketShops": "סיטי מרקט",
    "DorAlon": "דור אלון",
    "GoodPharm": "גוד פארם",
    "HaziHinam": "חצי חינם",
    "HetCohenNewSource": "ח. כהן",
    "Keshet": "קשת טעמים",
    "KingStore": "קינג סטור",
    "Maayan2000": "מעיין 2000",
    "MahsaniAShukNewSource": "מחסני השוק",
    "NetivHased": "נתיב החסד",
    "MeshnatYosef1": "משנת יוסף",
    "MeshnatYosef2": "משנת יוסף 2",
    "Osherad": "אושר עד",
    "Polizer": "פוליצר",
    "RamiLevy": "רמי לוי",
    "SalachDabach": "סאלח דבאח",
    "ShefaBarcartAshem": "שפע ברכת השם",
    "Shufersal": "שופרסל",
    "ShukAhir": "שוק העיר",
    "StopMarket": "סטופ מרקט",
    "SuperPharm": "סופר פארם",
    "SuperYuda": "סופר יודה",
    "SuperSapir": "סופר ספיר",
    "FreshMarketAndSuperDosh": "פרשמרקט / סופר דוש",
    "TivTaam": "טיב טעם",
    "VictoryNewSource": "ויקטורי",
    "Yellow": "יילו",
    "Yohananof": "יוחננוף",
    "ZolVeBegadol": "זול ובגדול",
    "Wolt": "וולט",
}

# תהליכי ההורדה (multiprocessing) מייבאים את הקובץ הזה מחדש; משתיקים שם את הלוגים של החבילה
if os.environ.get("IL_PRICES_QUIET"):
    try:
        from il_supermarket_scarper.utils import Logger as _PkgLogger

        _PkgLogger.change_logging_status(False)
    except Exception:  # noqa: BLE001
        pass

UNKNOWN = "לא ידוע"
NOTE_NO_STORE_FILE = "הרשת לא מפרסמת קובץ סניפים"

PRICE_RECORD_TAGS = {"item", "product", "line"}
STORE_RECORD_TAGS = {"store", "branch"}
FILE_NAME_RE = re.compile(r"(\d{9,13})-(\d+)-(?:(\d+)-)?(\d{8})")


# ---------------------------------------------------------------- utilities
def hebrew_console():
    """מוודא שהקונסולה מדפיסה עברית."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:  # noqa: BLE001
            pass


def load_cities():
    try:
        with open(CITIES_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


CITIES = load_cities()


def normalize_city(value):
    value = re.sub(r"\s+", " ", (value or "")).strip()
    if value.isdigit():
        if int(value) == 0:
            return ""
        return CITIES.get(str(int(value)), value)
    return value


def clean_text(value):
    value = re.sub(r"\s+", " ", (value or "")).strip()
    return "" if value.lower() in ("unknown", "null", "none") else value


def to_store_id(value):
    value = clean_text(value)
    if value.isdigit():
        return int(value)
    return value or None


def parse_file_name(name):
    """מחזיר (chain_id, store_id, date) משם הקובץ, או (None, None, None)."""
    m = FILE_NAME_RE.search(os.path.basename(name))
    if not m:
        return None, None, None
    chain_id, a, b, date = m.groups()
    store = b if b is not None else a
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    return chain_id, store, iso


def fmt_price(value):
    return f"{value:,.2f} ₪"


def print_table(headers, rows):
    """הדפסת טבלה פשוטה."""
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))


# ---------------------------------------------------------------- database
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    init_schema(conn)
    return conn


def init_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stores (
            chain      TEXT NOT NULL,
            store_id   INTEGER NOT NULL,
            store_name TEXT,
            city       TEXT,
            address    TEXT,
            notes      TEXT DEFAULT '',
            PRIMARY KEY (chain, store_id)
        );
        CREATE TABLE IF NOT EXISTS prices (
            chain    TEXT NOT NULL,
            store_id INTEGER NOT NULL,
            barcode  TEXT NOT NULL,
            name     TEXT,
            price    REAL NOT NULL,
            date     TEXT,
            PRIMARY KEY (chain, store_id, barcode)
        );
        CREATE TABLE IF NOT EXISTS products (
            barcode TEXT PRIMARY KEY,
            name    TEXT
        );
        CREATE TABLE IF NOT EXISTS price_history (
            chain    TEXT NOT NULL,
            store_id INTEGER NOT NULL,
            barcode  TEXT NOT NULL,
            price    REAL,
            date     TEXT NOT NULL,
            PRIMARY KEY (chain, store_id, barcode, date)
        );
        CREATE INDEX IF NOT EXISTS idx_history_barcode ON price_history(barcode);
        CREATE INDEX IF NOT EXISTS idx_prices_barcode ON prices(barcode);
        CREATE INDEX IF NOT EXISTS idx_stores_city ON stores(city);
        """
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(stores)")}
    if "notes" not in cols:
        conn.execute("ALTER TABLE stores ADD COLUMN notes TEXT DEFAULT ''")
    # גרסה ישנה של טבלת ההיסטוריה לא אפשרה NULL (= מוצר שנעלם מהסניף) - מעבירים לגרסה החדשה
    hist_cols = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(price_history)")}
    if hist_cols.get("price") == 1:
        conn.executescript(
            """
            ALTER TABLE price_history RENAME TO price_history_old;
            CREATE TABLE price_history (
                chain TEXT NOT NULL, store_id INTEGER NOT NULL, barcode TEXT NOT NULL,
                price REAL, date TEXT NOT NULL, PRIMARY KEY (chain, store_id, barcode, date)
            );
            INSERT INTO price_history SELECT * FROM price_history_old;
            DROP TABLE price_history_old;
            CREATE INDEX IF NOT EXISTS idx_history_barcode ON price_history(barcode);
            """
        )
    conn.commit()


# ---------------------------------------------------------------- XML parsing
def read_bytes(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def local_tag(tag):
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def iter_records(data, record_tags):
    """
    עובר על קובץ XML ומחזיר (header, record) לכל רשומה.
    header = שדות שנמצאו מחוץ לרשומות (ChainID, StoreID וכו').
    """
    from lxml import etree

    def _run(payload):
        header = {}
        depth_in_record = 0
        parser = etree.iterparse(
            io.BytesIO(payload), events=("start", "end"), recover=True, huge_tree=True
        )
        for event, elem in parser:
            tag = local_tag(elem.tag)
            if event == "start":
                if tag in record_tags or depth_in_record:
                    depth_in_record += 1
                continue
            if depth_in_record:
                depth_in_record -= 1
                if depth_in_record == 0 and tag in record_tags:
                    rec = {}
                    for child in elem:
                        ct = local_tag(child.tag)
                        if ct and ct not in rec:
                            rec[ct] = clean_text(child.text)
                    yield header, rec
                    elem.clear()
                    while elem.getprevious() is not None:
                        del elem.getparent()[0]
            else:
                if tag and tag not in header and len(elem) == 0:
                    header[tag] = clean_text(elem.text)

    try:
        yield from _run(data)
    except Exception:  # noqa: BLE001
        # ניסיון שני: פענוח ידני של הקידוד והסרת הצהרת XML
        text = None
        for enc in ("utf-8-sig", "utf-16", "cp1255", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except Exception:  # noqa: BLE001
                continue
        if text is None:
            return
        text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
        yield from _run(text.encode("utf-8"))


def pick(rec, *keys):
    for k in keys:
        v = rec.get(k)
        if v:
            return v
    return ""


def parse_store_file(path):
    """מחזיר רשימת (store_id, store_name, city, address, notes). מה שחסר בקובץ הרשת מסומן 'לא ידוע' ומצוין בהערות."""
    out = []
    for _hdr, rec in iter_records(read_bytes(path), STORE_RECORD_TAGS):
        sid = to_store_id(pick(rec, "storeid", "storeno", "branchid", "store_id", "id"))
        if sid is None:
            continue
        notes = []
        name = pick(rec, "storename", "branchname", "name", "store_name")
        if not name:
            name = f"סניף {sid}"
            notes.append("שם הסניף חסר בקובץ הרשת")
        city = normalize_city(pick(rec, "city", "cityname", "town"))
        if not city:
            city = UNKNOWN
            notes.append("העיר חסרה בקובץ הרשת")
        address = clean_text(pick(rec, "address", "street", "storeaddress"))
        if not address:
            address = UNKNOWN
            notes.append("הכתובת חסרה בקובץ הרשת")
        out.append((sid, name, city, address, "; ".join(notes)))
    return out


def parse_price_file(path):
    """מחזיר (store_id, date, [(barcode, name, price), ...])."""
    _chain_id, fn_store, fn_date = parse_file_name(path)
    store_id = None
    items = []
    for hdr, rec in iter_records(read_bytes(path), PRICE_RECORD_TAGS):
        if store_id is None:
            store_id = to_store_id(pick(hdr, "storeid", "store_id", "storeno"))
        barcode = clean_text(pick(rec, "itemcode", "barcode", "productcode", "code"))
        price_txt = pick(rec, "itemprice", "price", "unitprice", "itemprice1")
        if not barcode or not price_txt:
            continue
        try:
            price = float(price_txt.replace(",", ""))
        except ValueError:
            continue
        if price <= 0:
            continue
        name = pick(rec, "itemname", "itemnm", "manufactureitemdescription", "productname", "name")
        items.append((barcode, name, price))
    if store_id is None and fn_store:
        store_id = to_store_id(fn_store)
    return store_id, fn_date or dt.date.today().isoformat(), items


FILE_TS_RE = re.compile(r"-(\d{8})-?(\d{0,6})")


def file_sort_key(path):
    """(תאריך, שעה) משם הקובץ, כדי לקלוט קבצים בסדר כרונולוגי מדויק."""
    m = FILE_TS_RE.search(os.path.basename(path))
    if not m:
        return ("", "", os.path.basename(path))
    return (m.group(1), m.group(2), os.path.basename(path))


def dump_files():
    """כל הקבצים שהורדו: [(chain_folder, path)]."""
    result = []
    if not os.path.isdir(DUMPS_DIR):
        return result
    for folder in sorted(os.listdir(DUMPS_DIR)):
        full = os.path.join(DUMPS_DIR, folder)
        if folder == "status" or not os.path.isdir(full):
            continue
        for fn in sorted(os.listdir(full)):
            if fn.lower().endswith((".xml", ".gz")):
                result.append((folder, os.path.join(full, fn)))
    return result


def is_store_file(path):
    return "store" in os.path.basename(path).lower()


def is_price_full_file(path):
    return "pricefull" in os.path.basename(path).lower()


def parallel_parse(func, paths, workers):
    """מפענח קבצים במקביל (כמה תהליכים), ומחזיר את התוצאות בסדר המקורי, בחלונות קטנים כדי לחסוך זיכרון."""
    window = workers * 3
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i in range(0, len(paths), window):
            chunk = paths[i:i + window]
            futures = [pool.submit(func, p) for p in chunk]
            for p, fut in zip(chunk, futures):
                try:
                    yield p, fut.result(), None
                except Exception as exc:  # noqa: BLE001
                    yield p, None, exc


def import_dumps(conn, delete_after=True, workers=4):
    """פרסור כל הקבצים בתיקיית dumps והכנסה למסד הנתונים (בסדר כרונולוגי)."""
    files = dump_files()
    store_files = sorted(((c, p) for c, p in files if is_store_file(p)), key=lambda cp: file_sort_key(cp[1]))
    price_files = sorted(((c, p) for c, p in files if is_price_full_file(p)), key=lambda cp: file_sort_key(cp[1]))
    other = [p for c, p in files if not is_store_file(p) and not is_price_full_file(p)]

    print(f"\nמעבד {len(store_files)} קובצי סניפים ו-{len(price_files)} קובצי מחירים...")
    conn.execute("PRAGMA synchronous=OFF")
    stores_total = prices_total = 0

    folder_of = {p: c for c, p in files}
    for path, rows, exc in parallel_parse(parse_store_file, [p for _c, p in store_files], workers):
        folder = folder_of[path]
        chain = CHAIN_NAMES.get(folder, folder)
        try:
            if exc is not None:
                raise exc
            conn.executemany(
                "INSERT INTO stores(chain, store_id, store_name, city, address, notes) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(chain, store_id) DO UPDATE SET store_name=excluded.store_name, "
                "city=excluded.city, address=excluded.address, notes=excluded.notes",
                [(chain, *r) for r in rows],
            )
            conn.commit()
            stores_total += len(rows)
            print(f"  סניפים  {chain:<22} {len(rows):>5}  ({os.path.basename(path)})")
            if delete_after:
                os.remove(path)
        except Exception as exc:  # noqa: BLE001
            print(f"  שגיאה בקובץ {path}: {exc}")

    for i, (path, parsed, exc) in enumerate(parallel_parse(parse_price_file, [p for _c, p in price_files], workers), 1):
        folder = folder_of[path]
        chain = CHAIN_NAMES.get(folder, folder)
        try:
            if exc is not None:
                raise exc
            store_id, date, items = parsed
            if store_id is None or not items:
                print(f"  דילוג ({len(items)} פריטים, סניף {store_id}): {os.path.basename(path)}")
                if delete_after and store_id is not None:
                    os.remove(path)
                continue
            current = {b: (p, d) for b, p, d in conn.execute(
                "SELECT barcode, price, date FROM prices WHERE chain = ? AND store_id = ?", (chain, store_id)
            )}
            newest_in_db = max((d for _p, d in current.values()), default="")
            if newest_in_db > date:
                # קובץ ישן יותר ממה שכבר במסד - קליטה שלו הייתה מערבבת סדר זמנים
                print(f"  דילוג: {os.path.basename(path)} מתאריך {date}, במסד כבר יש {newest_in_db} לסניף הזה "
                      f"(לקליטת עבר מלאה: update --all-dates --rebuild)")
                if delete_after:
                    os.remove(path)
                continue
            # נתוני עבר (price_history): תמונת בסיס בפעם הראשונה שסניף נראה, ואחר כך רק שינויים.
            # מחיר NULL בהיסטוריה = המוצר לא הופיע יותר בקובץ הסניף באותו תאריך.
            item_codes = {b for b, _n, _p in items}
            if not current:
                history_rows = [(chain, store_id, b, p, date) for b, _n, p in items]
            else:
                history_rows = [(chain, store_id, b, p, date) for b, _n, p in items
                                if b not in current or abs(current[b][0] - p) > 0.001]
                history_rows += [(chain, store_id, b, None, date) for b in current if b not in item_codes]
            conn.executemany(
                "INSERT OR REPLACE INTO price_history(chain, store_id, barcode, price, date) VALUES (?,?,?,?,?)",
                history_rows,
            )
            conn.executemany(
                "INSERT INTO prices(chain, store_id, barcode, name, price, date) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(chain, store_id, barcode) DO UPDATE SET name=excluded.name, "
                "price=excluded.price, date=excluded.date WHERE excluded.date >= prices.date",
                [(chain, store_id, b, n, p, date) for b, n, p in items],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO products(barcode, name) VALUES (?,?)",
                [(b, n) for b, n, _p in items if n],
            )
            # קובץ PriceFull הוא תמונה מלאה של הסניף - מוצרים שלא מופיעים בו יותר נמחקים
            conn.execute(
                "DELETE FROM prices WHERE chain = ? AND store_id = ? AND date < ?",
                (chain, store_id, date),
            )
            conn.commit()
            prices_total += len(items)
            print(f"  מחירים  {chain:<22} סניף {str(store_id):<6} {len(items):>6} פריטים  [{i}/{len(price_files)}]")
            if delete_after:
                os.remove(path)
        except Exception as exc:  # noqa: BLE001
            print(f"  שגיאה בקובץ {path}: {exc} (הקובץ נשמר וייקלט בניסיון הבא)")

    if delete_after:
        for p in other:
            try:
                os.remove(p)
            except OSError:
                pass
    conn.execute("PRAGMA synchronous=NORMAL")
    print(f"\nנקלטו {stores_total:,} סניפים ו-{prices_total:,} רשומות מחיר.")


# ---------------------------------------------------------------- scraping
class SqliteStatusDB:
    """
    מסד סטטוס להורדות של il-supermarket-scraper על בסיס SQLite.
    מחליף את ברירת המחדל (קובץ JSON שנכתב מחדש בכל אירוע ונעשה איטי מאוד עם אלפי קבצים).
    נשמר רק מה שנחוץ: אילו קבצים כבר הורדו ונקלטו בהצלחה.
    """

    def __init__(self, database_name):
        self.database_name = database_name.replace(" ", "_").lower()
        self.path = os.path.join(STATUS_DIR, f"{self.database_name}.sqlite")
        self._conn = None
        os.makedirs(STATUS_DIR, exist_ok=True)
        self._migrate_from_json()

    # החיבור נפתח בכל תהליך בנפרד (האובייקט עובר בין תהליכים)
    def __getstate__(self):
        state = self.__dict__.copy()
        state["_conn"] = None
        return state

    def _db(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.path, timeout=60)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS downloaded (file_name TEXT PRIMARY KEY, ts TEXT)"
            )
            self._conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            self._conn.commit()
        return self._conn

    def _migrate_from_json(self):
        """מעבר חד-פעמי מקובץ ה-JSON של החבילה, אם קיים ותקין."""
        json_path = os.path.join(STATUS_DIR, f"{self.database_name}.json")
        if not os.path.exists(json_path):
            return
        try:
            with open(json_path, encoding="utf-8") as fh:
                data = json.load(fh)
            names = [d.get("file_name") for d in data.get("verified_downloads", []) if d.get("file_name")]
            db = self._db()
            db.executemany("INSERT OR IGNORE INTO downloaded(file_name, ts) VALUES (?, ?)",
                           [(n, "") for n in names])
            db.commit()
        except Exception:  # noqa: BLE001
            pass  # קובץ פגום: עדיף להוריד שוב מאשר לדלג על קבצים
        os.remove(json_path)

    def get_database_name(self):
        return self.database_name

    def insert_document(self, collection_name, document):
        if collection_name == "verified_downloads" and document.get("file_name"):
            db = self._db()
            db.execute("INSERT OR IGNORE INTO downloaded(file_name, ts) VALUES (?, ?)",
                       (document["file_name"], str(document.get("system_timestamp", ""))))
            db.commit()
            self._update_last_modified()

    def insert_documents(self, collection_name, documents):
        for d in documents:
            self.insert_document(collection_name, d)

    def already_downloaded(self, collection_name, query):
        if collection_name != "verified_downloads" or "file_name" not in query:
            return False
        row = self._db().execute("SELECT 1 FROM downloaded WHERE file_name = ?", (query["file_name"],)).fetchone()
        return row is not None

    def _update_last_modified(self):
        self._db().execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('last_modified', ?)",
                           (dt.datetime.now().isoformat(),))

    def get_last_modified(self):
        row = self._db().execute("SELECT value FROM meta WHERE key = 'last_modified'").fetchone()
        if not row:
            return None
        try:
            return dt.datetime.fromisoformat(row[0])
        except ValueError:
            return None


def all_chain_names():
    from il_supermarket_scarper import ScraperFactory

    return ScraperFactory.all_scrapers_name()


def count_dump_files():
    return len(dump_files())


def run_scrape(chains, file_types, when_date, limit, timeout_minutes, workers):
    """מריץ את il-supermarket-scraper על הרשתות המבוקשות."""
    from il_supermarket_scarper import ScarpingTask
    from il_supermarket_scarper.utils import Logger

    Logger.change_logging_status(False)
    os.environ["IL_PRICES_QUIET"] = "1"
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.makedirs(DUMPS_DIR, exist_ok=True)
    task = ScarpingTask(
        enabled_scrapers=chains,
        files_types=file_types,
        multiprocessing=workers,
        output_configuration={"output_mode": "disk", "base_storage_path": DUMPS_DIR},
        status_configuration={"database_type": "json", "base_path": STATUS_DIR},
    )
    from il_supermarket_scarper.utils.folders_name import DumpFolderNames

    for name in chains:
        task.runner._status_databases[name] = SqliteStatusDB(DumpFolderNames[name].value)
    start = time.time()
    thread = task.start(limit=limit, when_date=when_date)
    last_report = 0
    while thread.is_alive():
        thread.join(5)
        elapsed = time.time() - start
        if elapsed - last_report >= 30:
            last_report = elapsed
            print(f"  ... {int(elapsed // 60)} דק', {count_dump_files()} קבצים הורדו עד כה")
        if elapsed > timeout_minutes * 60:
            print(f"  עברו {timeout_minutes} דקות - עוצר את ההורדה וממשיך לעיבוד.")
            task.stop()
            thread.join(60)
            break
    print(f"  ההורדה הסתיימה אחרי {int((time.time() - start) // 60)} דק'. {count_dump_files()} קבצים.")


def forget_downloaded_store_files():
    """מוחק מקובצי הסטטוס של החבילה את הרישום של קובצי סניפים שכבר הורדו."""
    if not os.path.isdir(STATUS_DIR):
        return
    for fn in os.listdir(STATUS_DIR):
        path = os.path.join(STATUS_DIR, fn)
        if fn.endswith(".sqlite"):
            db = sqlite3.connect(path)
            db.execute("DELETE FROM downloaded WHERE lower(file_name) LIKE '%store%'")
            db.commit()
            db.close()
            continue
        if not fn.endswith(".json"):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            downloads = data.get("verified_downloads")
            if isinstance(downloads, list):
                data["verified_downloads"] = [
                    d for d in downloads if "store" not in str(d.get("file_name", "")).lower()
                ]
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            continue


def folders_with_price_files():
    return {folder for folder, p in dump_files() if is_price_full_file(p)}


def cmd_update(args):
    hebrew_console()
    available = all_chain_names()
    if args.chains:
        chains = []
        for c in args.chains.split(","):
            c = c.strip().upper()
            if c not in available:
                sys.exit(f"רשת לא מוכרת: {c}. רשתות אפשריות: {', '.join(available)}")
            chains.append(c)
    else:
        chains = available

    if args.all_dates:
        dates = [None]
    elif args.date:
        dates = [dt.datetime.strptime(args.date, "%Y-%m-%d")]
    else:
        today = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        dates = [today, today - dt.timedelta(days=1)]

    print(f"מעדכן {len(chains)} רשתות. קבצים יישמרו זמנית ב-{DUMPS_DIR}")
    from il_supermarket_scarper import FileTypesFilters
    from il_supermarket_scarper.utils.folders_name import DumpFolderNames

    conn = connect()
    if args.rebuild:
        print("בנייה מחדש: מוחק את המחירים, הסניפים וההיסטוריה במסד ואת זיכרון ההורדות של החבילה.")
        for table in ("prices", "price_history", "stores", "products"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        if os.path.isdir(STATUS_DIR):
            for fn in os.listdir(STATUS_DIR):
                os.remove(os.path.join(STATUS_DIR, fn))
    if args.all_dates:
        # כל התאריכים שקיימים באתרים: עובדים בקבוצות רשתות, וקולטים כל קבוצה בסדר כרונולוגי לפני הבאה
        batch_size = max(1, args.workers)
        batches = [chains[i:i + batch_size] for i in range(0, len(chains), batch_size)]
        for i, batch in enumerate(batches, 1):
            print(f"\n[{i}/{len(batches)}] מוריד את כל הקבצים הקיימים באתר עבור: {', '.join(batch)}")
            run_scrape(batch, [FileTypesFilters.STORE_FILE.name, FileTypesFilters.PRICE_FULL_FILE.name],
                       None, args.limit, args.timeout, args.workers)
            import_dumps(conn, delete_after=not args.keep_files, workers=args.workers)
        conn.execute("VACUUM")
        cmd_stats(args, conn)
        return
    if args.force_stores:
        # שוכחים אילו קובצי סניפים כבר הורדו, כדי שיירדו וייקלטו מחדש
        forget_downloaded_store_files()
        conn.execute("DELETE FROM stores")
        conn.commit()
        print("רשימת הסניפים אופסה ותיבנה מחדש מקובצי הרשתות.")
    steps = 1 if args.stores_only else len(dates) + 1
    store_date = dates[0] if dates[0] is not None else None
    print(f"\n[1/{steps}] מוריד קובצי סניפים עבור {len(chains)} רשתות...")
    run_scrape(chains, [FileTypesFilters.STORE_FILE.name], store_date, args.limit, args.timeout, args.workers)
    # רשתות שלא פרסמו קובץ סניפים היום ואין להן סניפים במסד - מורידים קובץ סניפים אחד מכל תאריך שהוא
    have_store_file = {folder for folder, p in dump_files() if is_store_file(p)}
    in_db = {row[0] for row in conn.execute("SELECT DISTINCT chain FROM stores")}
    need_stores = [
        c for c in chains
        if DumpFolderNames[c].value not in have_store_file
        and CHAIN_NAMES.get(DumpFolderNames[c].value, DumpFolderNames[c].value) not in in_db
    ]
    if need_stores:
        print(f"  אין עדיין רשימת סניפים עבור {', '.join(need_stores)} - מוריד קובץ סניפים ישן יותר.")
        run_scrape(need_stores, [FileTypesFilters.STORE_FILE.name], None, 1, args.timeout, args.workers)

    if args.stores_only:
        import_dumps(conn, delete_after=not args.keep_files, workers=args.workers)
        cmd_stats(args, conn)
        return

    # רשתות שכבר יש להן במסד מחירים מהתאריך המבוקש לא צריכות ניסיון חוזר לתאריך קודם
    latest_in_db = dict(conn.execute("SELECT chain, MAX(date) FROM prices GROUP BY chain").fetchall())

    def has_prices_for(chain_key, when):
        name = CHAIN_NAMES.get(DumpFolderNames[chain_key].value, DumpFolderNames[chain_key].value)
        return when is not None and (latest_in_db.get(name) or "") >= when.strftime("%Y-%m-%d")

    remaining = list(chains)
    for i, when in enumerate(dates):
        if not remaining:
            break
        label = "כל התאריכים" if when is None else when.strftime("%Y-%m-%d")
        print(f"\n[{i + 2}/{steps}] מוריד קובצי מחירים לתאריך {label} עבור {len(remaining)} רשתות...")
        run_scrape(remaining, [FileTypesFilters.PRICE_FULL_FILE.name], when, args.limit, args.timeout, args.workers)
        done = folders_with_price_files()
        remaining = [
            c for c in remaining
            if DumpFolderNames[c].value not in done and not has_prices_for(c, when)
        ]
        if remaining and i + 1 < len(dates):
            print(f"  ללא קובצי מחירים עדיין: {', '.join(remaining)} - מנסה תאריך קודם.")
    if remaining:
        print(f"\nלא התקבלו קובצי מחירים חדשים מהרשתות: {', '.join(remaining)}"
              " (כנראה האתר חסום או שאין עדכון היום; המחירים הקודמים שלהן נשארים במסד).")

    import_dumps(conn, delete_after=not args.keep_files, workers=args.workers)
    cmd_stats(args, conn)


# ---------------------------------------------------------------- queries
def cmd_stats(_args, conn=None):
    hebrew_console()
    conn = conn or connect()
    chains = conn.execute("SELECT COUNT(DISTINCT chain) FROM prices").fetchone()[0]
    stores = conn.execute("SELECT COUNT(DISTINCT chain || '/' || store_id) FROM prices").fetchone()[0]
    products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    rows = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    latest = conn.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    hist = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM price_history").fetchone()
    print("\nמצב מסד הנתונים:")
    if hist[0]:
        print(f"  היסטוריה: {hist[0]:,} רשומות, מתאריך {hist[1]} עד {hist[2]}")
    print(f"  רשתות: {chains}   סניפים: {stores:,}   מוצרים: {products:,}   רשומות מחיר: {rows:,}   עדכון אחרון: {latest or '-'}")
    per_chain = conn.execute(
        "SELECT chain, COUNT(DISTINCT store_id), COUNT(*), MIN(date), MAX(date) FROM prices GROUP BY chain ORDER BY chain"
    ).fetchall()
    no_store_file = {r[0] for r in conn.execute(
        "SELECT DISTINCT chain FROM prices WHERE chain NOT IN (SELECT DISTINCT chain FROM stores)"
    )}
    if per_chain:
        print_table(
            ["רשת", "סניפים", "מחירים", "תאריך מחירים", "הערות"],
            [
                (c, s, f"{n:,}", d1 if d1 == d2 else f"{d1} עד {d2}", NOTE_NO_STORE_FILE if c in no_store_file else "")
                for c, s, n, d1, d2 in per_chain
            ],
        )


def cmd_search(args):
    hebrew_console()
    conn = connect()
    words = [w for w in args.query.split() if w]
    if not words:
        sys.exit("יש לציין טקסט לחיפוש.")
    if args.query.strip().isdigit():
        where = "p.barcode LIKE ?"
        params = [args.query.strip() + "%"]
    else:
        where = " AND ".join("p.name LIKE ?" for _ in words)
        params = [f"%{w}%" for w in words]
    rows = conn.execute(
        f"""
        SELECT p.barcode, p.name, COUNT(pr.barcode), MIN(pr.price), MAX(pr.price)
        FROM products p LEFT JOIN prices pr ON pr.barcode = p.barcode
        WHERE {where}
        GROUP BY p.barcode
        ORDER BY COUNT(pr.barcode) DESC, p.name
        LIMIT ?
        """,
        params + [args.limit],
    ).fetchall()
    if not rows:
        print("לא נמצאו מוצרים תואמים.")
        return
    print(f"נמצאו {len(rows)} מוצרים (מציג עד {args.limit}):\n")
    print_table(
        ["ברקוד", "שם", "סניפים", "מחיר מינ'", "מחיר מקס'"],
        [
            (b, n, c, fmt_price(lo) if lo else "-", fmt_price(hi) if hi else "-")
            for b, n, c, lo, hi in rows
        ],
    )
    print("\nלהצגת מחירים: il-prices price <ברקוד>")


def city_filter(city):
    if not city:
        return "", []
    return " AND s.city LIKE ? ", [f"%{city.strip()}%"]


MAX_AGE_DAYS = 7


def date_filter(date, include_old=False):
    """סינון לפי תאריך: תאריך מדויק, או ברירת מחדל - רק מחירים מ-7 הימים האחרונים."""
    if date:
        return " AND pr.date = ? ", [date]
    if include_old:
        return "", []
    cutoff = (dt.date.today() - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
    return " AND pr.date >= ? ", [cutoff]


def count_old(conn, where_sql, params, include_old, date):
    """כמה רשומות ישנות (מעל 7 ימים) הושמטו, כדי לציין זאת בפלט."""
    if include_old or date:
        return 0
    cutoff = (dt.date.today() - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
    return conn.execute(f"SELECT COUNT(*) FROM prices pr LEFT JOIN stores s ON s.chain = pr.chain AND s.store_id = pr.store_id "
                        f"WHERE {where_sql} AND pr.date < ?", params + [cutoff]).fetchone()[0]


def old_note(n):
    return (f"הושמטו {n} מחירים ישנים מ-{MAX_AGE_DAYS} ימים (סניפים שהרשת הפסיקה לפרסם). "
            f"להצגתם הוסיפו --include-old") if n else ""


def date_summary(dates):
    """שורת סיכום על תאריכי המחירים, עם אזהרה אם הם לא מאותו יום."""
    dates = sorted(set(d for d in dates if d))
    if not dates:
        return "תאריך המחירים: לא ידוע"
    if len(dates) == 1:
        return f"כל המחירים מתאריך {dates[0]}"
    return (f"שימו לב: המחירים מתאריכים שונים ({dates[0]} עד {dates[-1]}). "
            f"התאריך מופיע ליד כל מחיר; להשוואה של יום אחד בלבד הוסיפו --date YYYY-MM-DD")


def cmd_price(args):
    hebrew_console()
    conn = connect()
    barcode = args.barcode.strip()
    cf, cparams = city_filter(args.city)
    df, dparams = date_filter(args.date, args.include_old)
    old = count_old(conn, f"pr.barcode = ? {cf}", [barcode] + cparams, args.include_old, args.date)
    rows = conn.execute(
        f"""
        SELECT pr.price, pr.chain, COALESCE(s.store_name, 'סניף ' || pr.store_id),
               COALESCE(s.city, ?), COALESCE(s.address, ?), pr.date, pr.name,
               CASE WHEN s.store_id IS NULL THEN ? ELSE COALESCE(s.notes, '') END
        FROM prices pr LEFT JOIN stores s ON s.chain = pr.chain AND s.store_id = pr.store_id
        WHERE pr.barcode = ? {cf} {df}
        ORDER BY pr.price ASC, pr.chain
        LIMIT ?
        """,
        [UNKNOWN, UNKNOWN, NOTE_NO_STORE_FILE, barcode] + cparams + dparams + [args.limit],
    ).fetchall()
    if not rows:
        where = f" בעיר '{args.city}'" if args.city else ""
        when = f" מתאריך {args.date}" if args.date else ""
        print(f"לא נמצאו מחירים לברקוד {barcode}{where}{when}.")
        if old:
            print(old_note(old))
        return
    name = next((r[6] for r in rows if r[6]), "")
    print(f"{name}  (ברקוד {barcode})")
    if args.city:
        print(f"סינון לעיר: {args.city}")
    print(f"{len(rows)} סניפים, מהזול ליקר. הזול ביותר: {fmt_price(rows[0][0])}, היקר ביותר: {fmt_price(rows[-1][0])}")
    print(date_summary(r[5] for r in rows))
    if old:
        print(old_note(old))
    print()
    print_table(
        ["#", "מחיר", "תאריך", "רשת", "סניף", "עיר", "כתובת", "הערות"],
        [
            (i, fmt_price(p), d, ch, sn, ci, ad, nt)
            for i, (p, ch, sn, ci, ad, d, _n, nt) in enumerate(rows, 1)
        ],
    )


def cmd_history(args):
    hebrew_console()
    conn = connect()
    barcode = args.barcode.strip()
    cf, cparams = city_filter(args.city)
    chf, chparams = ("", [])
    if args.chain:
        chf, chparams = " AND pr.chain LIKE ? ", [f"%{args.chain}%"]
    name = conn.execute("SELECT name FROM products WHERE barcode = ?", (barcode,)).fetchone()
    print(f"{name[0] if name else ''}  (ברקוד {barcode})")
    rows = conn.execute(
        f"""
        SELECT pr.chain, pr.store_id, COALESCE(s.store_name, 'סניף ' || pr.store_id), COALESCE(s.city, ?),
               pr.price, pr.date, 'נוכחי' AS kind
        FROM prices pr LEFT JOIN stores s ON s.chain = pr.chain AND s.store_id = pr.store_id
        WHERE pr.barcode = ? {cf} {chf}
        UNION ALL
        SELECT pr.chain, pr.store_id, COALESCE(s.store_name, 'סניף ' || pr.store_id), COALESCE(s.city, ?),
               pr.price, pr.date, 'היסטוריה'
        FROM price_history pr LEFT JOIN stores s ON s.chain = pr.chain AND s.store_id = pr.store_id
        WHERE pr.barcode = ? {cf} {chf}
        """,
        [UNKNOWN, barcode] + cparams + chparams + [UNKNOWN, barcode] + cparams + chparams,
    ).fetchall()
    if not rows:
        print("אין נתונים לברקוד הזה" + (f" בעיר '{args.city}'" if args.city else "") + ".")
        return
    by_store = defaultdict(dict)
    info = {}
    for chain, sid, sname, city, price, date, _kind in rows:
        by_store[(chain, sid)][date] = price
        info[(chain, sid)] = (chain, sname, city)
    # תמונה כללית לפי תאריך: מחיר מינימלי, ממוצע ומקסימלי בכל הסניפים שנכללו
    dates = sorted({d for st in by_store.values() for d in st})
    print(f"{len(by_store)} סניפים, {len(dates)} תאריכים ({dates[0]} עד {dates[-1]}).")
    print("ההיסטוריה נצברת מכל עדכון יומי: תמונת בסיס ביום הראשון של כל סניף, ואחריה רק שינויים.\n")
    summary = []
    for d in dates:
        ps = []
        for st in by_store.values():
            # המחיר שהיה בתוקף בסניף בתאריך d = הרשומה האחרונה שאינה מאוחרת ל-d (NULL = לא נמכר)
            earlier = [x for x in st if x <= d]
            if earlier:
                p = st[max(earlier)]
                if p is not None:
                    ps.append(p)
        if ps:
            summary.append((d, len(ps), fmt_price(min(ps)), fmt_price(sum(ps) / len(ps)), fmt_price(max(ps))))
        else:
            summary.append((d, 0, "-", "-", "-"))
    print_table(["תאריך", "סניפים", "מינימום", "ממוצע", "מקסימום"], summary)
    def collapse(st):
        """משאיר רק נקודות שבהן המחיר באמת השתנה (הרשומה הנוכחית חוזרת על המחיר האחרון)."""
        out = []
        for d, p in sorted(st.items()):
            if not out or out[-1][1] != p:
                out.append((d, p))
        return out

    changed = [(k, collapse(st)) for k, st in by_store.items()]
    changed = [(k, tl) for k, tl in changed if len(tl) > 1]
    if changed:
        print(f"\nסניפים שבהם המחיר השתנה ({len(changed)}), לפי מספר שינויים:")
        changed.sort(key=lambda kv: -len(kv[1]))
        table = []
        for k, st in changed[: args.limit]:
            chain, sname, city = info[k]
            timeline = "  |  ".join(f"{d}: {fmt_price(p) if p is not None else 'לא נמכר'}" for d, p in st)
            table.append((chain, sname, city, timeline))
        print_table(["רשת", "סניף", "עיר", "מחירים לפי תאריך"], table)
    else:
        print("\nעדיין לא נרשם שינוי מחיר באף סניף. הרצת update יומית תתחיל לצבור היסטוריה.")


def read_basket(path):
    """קורא קובץ סל: ברקוד בכל שורה, אופציונלית כמות אחרי רווח/פסיק. # = הערה."""
    items = {}
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = re.split(r"[\s,;]+", line)
            barcode = parts[0]
            qty = 1.0
            if len(parts) > 1:
                try:
                    qty = float(parts[1])
                except ValueError:
                    qty = 1.0
            items[barcode] = items.get(barcode, 0) + qty
    return items


def cmd_basket(args):
    hebrew_console()
    conn = connect()
    if not os.path.exists(args.file):
        sys.exit(f"הקובץ {args.file} לא נמצא.")
    basket = read_basket(args.file)
    if not basket:
        sys.exit("קובץ הסל ריק.")
    barcodes = list(basket)
    names = {
        b: n
        for b, n in conn.execute(
            f"SELECT barcode, name FROM products WHERE barcode IN ({','.join('?' * len(barcodes))})",
            barcodes,
        )
    }
    unknown = [b for b in barcodes if b not in names]
    cf, cparams = city_filter(args.city)
    df, dparams = date_filter(args.date, args.include_old)
    old = count_old(conn, f"pr.barcode IN ({','.join('?' * len(barcodes))}) {cf}", barcodes + cparams,
                    args.include_old, args.date)
    rows = conn.execute(
        f"""
        SELECT pr.chain, pr.store_id, pr.barcode, pr.price,
               COALESCE(s.store_name, 'סניף ' || pr.store_id), COALESCE(s.city, ?), COALESCE(s.address, ?),
               pr.date, CASE WHEN s.store_id IS NULL THEN ? ELSE COALESCE(s.notes, '') END
        FROM prices pr LEFT JOIN stores s ON s.chain = pr.chain AND s.store_id = pr.store_id
        WHERE pr.barcode IN ({','.join('?' * len(barcodes))}) {cf} {df}
        """,
        [UNKNOWN, UNKNOWN, NOTE_NO_STORE_FILE] + barcodes + cparams + dparams,
    ).fetchall()

    store_prices = defaultdict(dict)   # (chain, store_id) -> {barcode: price}
    price_dates = {}                   # (chain, store_id, barcode) -> date
    store_info = {}
    for chain, sid, barcode, price, sname, city, address, date, notes in rows:
        key = (chain, sid)
        if barcode not in store_prices[key] or price < store_prices[key][barcode]:
            store_prices[key][barcode] = price
            price_dates[(chain, sid, barcode)] = date
        store_info[key] = (chain, sname, city, address, notes)

    print(f"סל של {len(barcodes)} מוצרים" + (f" בעיר '{args.city}'" if args.city else " בכל הארץ")
          + (f", מחירים מתאריך {args.date} בלבד" if args.date else "") + ":")
    if old:
        print(old_note(old))
    for b in barcodes:
        q = basket[b]
        qtxt = f" x{q:g}" if q != 1 else ""
        print(f"  {b}  {names.get(b, '(לא נמצא במסד)')}{qtxt}")
    if unknown:
        print(f"\nאזהרה: {len(unknown)} ברקודים לא נמצאו בכלל במסד: {', '.join(unknown)}")
    available = [b for b in barcodes if any(b in sp for sp in store_prices.values())]
    if not available:
        print("\nאין נתוני מחיר לאף מוצר בסל" + (" בעיר זו." if args.city else "."))
        return
    if len(available) < len(barcodes):
        missing = [b for b in barcodes if b not in available]
        print(f"\nמוצרים ללא מחיר באף סניף{' בעיר זו' if args.city else ''} (יושמטו מהחישוב): {', '.join(missing)}")

    def total_for(key, subset):
        sp = store_prices[key]
        return sum(sp[b] * basket[b] for b in subset)

    def label(key):
        chain, sname, city, address, notes = store_info[key]
        text = f"{chain} - {sname} ({city}, {address})"
        return text + (f"  [הערה: {notes}]" if notes else "")

    def store_dates(key, subset):
        chain, sid = key
        return sorted(set(price_dates.get((chain, sid, b), "") for b in subset))

    def dates_text(key, subset):
        ds = store_dates(key, subset)
        return ds[0] if len(ds) == 1 else f"{ds[0]} עד {ds[-1]}"

    # --- 1. הסניף הזול ביותר לכל הסל
    print("\n" + "=" * 70)
    print("1) הסניף הזול ביותר לקניית כל הסל במקום אחד")
    print("=" * 70)
    full = [k for k, sp in store_prices.items() if all(b in sp for b in available)]
    best_single = None
    if full:
        ranked = sorted(full, key=lambda k: total_for(k, available))
        best_single = (ranked[0], total_for(ranked[0], available))
        print(f"{len(full)} סניפים מוכרים את כל {len(available)} המוצרים. הזולים ביותר:")
        print(date_summary(price_dates.get((k[0], k[1], b)) for k in ranked[: args.top] for b in available) + "\n")
        print_table(
            ["#", "סה\"כ", "תאריך המחירים", "סניף"],
            [(i, fmt_price(total_for(k, available)), dates_text(k, available), label(k))
             for i, k in enumerate(ranked[: args.top], 1)],
        )
    else:
        print("אף סניף לא מוכר את כל המוצרים בסל. הסניפים עם הכיסוי הטוב ביותר:\n")
        ranked = sorted(
            store_prices,
            key=lambda k: (-sum(1 for b in available if b in store_prices[k]),
                           total_for(k, [b for b in available if b in store_prices[k]])),
        )
        table = []
        for i, k in enumerate(ranked[: args.top], 1):
            have = [b for b in available if b in store_prices[k]]
            table.append((i, f"{len(have)}/{len(available)}", fmt_price(total_for(k, have)), dates_text(k, have), label(k)))
        print_table(["#", "מוצרים", "סה\"כ (לחלקי)", "תאריך המחירים", "סניף"], table)

    # --- 2. פיצול אופטימלי
    print("\n" + "=" * 70)
    print("2) הפיצול האופטימלי - כל מוצר בסניף הזול ביותר שלו")
    print("=" * 70)
    per_item_best = {}
    for b in available:
        cands = [(sp[b], k) for k, sp in store_prices.items() if b in sp]
        per_item_best[b] = min(cands)
    split_total = sum(p * basket[b] for b, (p, _k) in per_item_best.items())
    by_store = defaultdict(list)
    for b, (p, k) in per_item_best.items():
        by_store[k].append((b, p))
    print(f"סה\"כ {fmt_price(split_total)} ב-{len(by_store)} סניפים")
    print(date_summary(price_dates.get((k[0], k[1], b)) for b, (_p, k) in per_item_best.items()))
    if best_single:
        saving = best_single[1] - split_total
        print(f"חיסכון לעומת קנייה במקום אחד: {fmt_price(saving)} ({saving / best_single[1] * 100:.1f}%)")
    for k, lst in sorted(by_store.items(), key=lambda kv: -sum(p * basket[b] for b, p in kv[1])):
        sub = sum(p * basket[b] for b, p in lst)
        print(f"\n  {label(k)}  -  {len(lst)} מוצרים, {fmt_price(sub)}")
        for b, p in sorted(lst, key=lambda x: -x[1]):
            q = basket[b]
            qtxt = f" x{q:g}" if q != 1 else ""
            print(f"      {fmt_price(p):>12}{qtxt:<5} {price_dates.get((k[0], k[1], b), '')}  {b}  {names.get(b, '')}")

    # --- 3. פיצול מוגבל למספר סניפים
    if args.max_stores and args.max_stores < len(by_store):
        print("\n" + "=" * 70)
        print(f"3) הפיצול הטוב ביותר עם עד {args.max_stores} סניפים")
        print("=" * 70)
        candidates = set(k for _p, k in per_item_best.values())
        coverage_ranked = sorted(
            store_prices,
            key=lambda k: (-sum(1 for b in available if b in store_prices[k]),
                           total_for(k, [b for b in available if b in store_prices[k]])),
        )
        candidates.update(coverage_ranked[:20])
        candidates = list(candidates)[:28]
        best = None
        for n in range(1, args.max_stores + 1):
            for combo in itertools.combinations(candidates, n):
                total = 0.0
                covered = 0
                for b in available:
                    ps = [store_prices[k][b] for k in combo if b in store_prices[k]]
                    if ps:
                        covered += 1
                        total += min(ps) * basket[b]
                score = (-covered, total)
                if best is None or score < best[0]:
                    best = (score, combo)
        (neg_cov, total), combo = best
        print(f"כיסוי {-neg_cov}/{len(available)} מוצרים, סה\"כ {fmt_price(total)}:")
        for k in combo:
            got = [b for b in available if b in store_prices[k]
                   and store_prices[k][b] == min(store_prices[c][b] for c in combo if b in store_prices[c])]
            print(f"  {label(k)}  -  {len(got)} מוצרים")


# ---------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(prog="il-prices", description="השוואת מחירי סופרמרקט בישראל ברמת סניף")
    sub = p.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("update", help="הורדה ועדכון יומי")
    u.add_argument("--chains", help="רשימת רשתות מופרדות בפסיק (ברירת מחדל: כולן), למשל RAMI_LEVY,SHUFERSAL")
    u.add_argument("--limit", type=int, help="מספר קבצים מקסימלי לרשת (לבדיקות)")
    u.add_argument("--date", help="תאריך YYYY-MM-DD (ברירת מחדל: היום, ואם אין - אתמול)")
    u.add_argument("--all-dates", action="store_true", help="הורדת כל הקבצים שקיימים באתר, לא רק של היום")
    u.add_argument("--timeout", type=int, default=90, help="דקות מקסימום להורדה (ברירת מחדל 90)")
    u.add_argument("--workers", type=int, default=4, help="מספר רשתות שיורדות במקביל (ברירת מחדל 4)")
    u.add_argument("--keep-files", action="store_true", help="לא למחוק את קובצי ה-XML אחרי הקליטה")
    u.add_argument("--stores-only", action="store_true", help="לעדכן רק את רשימת הסניפים, בלי מחירים")
    u.add_argument("--force-stores", action="store_true", help="לבנות מחדש את רשימת הסניפים מקובצי הרשתות")
    u.add_argument("--rebuild", action="store_true", help="למחוק את כל המסד ולבנות מחדש (בשילוב עם --all-dates)")
    u.set_defaults(func=cmd_update)

    s = sub.add_parser("search", help="חיפוש ברקודים לפי שם מוצר")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(func=cmd_search)

    pr = sub.add_parser("price", help="כל הסניפים מהזול ליקר")
    pr.add_argument("barcode")
    pr.add_argument("--city", help="סינון לעיר")
    pr.add_argument("--date", help="להציג רק מחירים מתאריך מסוים (YYYY-MM-DD)")
    pr.add_argument("--include-old", action="store_true", help="לכלול גם מחירים ישנים מ-7 ימים")
    pr.add_argument("--limit", type=int, default=50)
    pr.set_defaults(func=cmd_price)

    h = sub.add_parser("history", help="נתוני עבר: שינויי מחיר של מוצר לאורך זמן")
    h.add_argument("barcode")
    h.add_argument("--city", help="סינון לעיר")
    h.add_argument("--chain", help="סינון לרשת (חלק מהשם)")
    h.add_argument("--limit", type=int, default=30, help="כמה סניפים להציג בפירוט")
    h.set_defaults(func=cmd_history)

    b = sub.add_parser("basket", help="הסניף הזול לסל ופיצול אופטימלי")
    b.add_argument("file", help="קובץ טקסט עם ברקוד בכל שורה (אופציונלי: כמות אחרי רווח)")
    b.add_argument("--city", help="סינון לעיר")
    b.add_argument("--date", help="להשתמש רק במחירים מתאריך מסוים (YYYY-MM-DD)")
    b.add_argument("--include-old", action="store_true", help="לכלול גם מחירים ישנים מ-7 ימים")
    b.add_argument("--top", type=int, default=5, help="כמה סניפים להציג")
    b.add_argument("--max-stores", type=int, help="פיצול מוגבל למספר סניפים (למשל 2)")
    b.set_defaults(func=cmd_basket)

    st = sub.add_parser("stats", help="מצב מסד הנתונים")
    st.set_defaults(func=cmd_stats)
    return p


def main():
    hebrew_console()
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
