# -*- coding: utf-8 -*-
"""
דוח מצב: כמה תופסים בענן, כמה נשאר בדיסק, ועל מה האתר מצביע.

הקובץ הזה קורא בלבד. אין בו PUT, POST או DELETE, ואפשר להריץ אותו בכל רגע
בלי לשנות דבר. מה שאי אפשר לקבוע נכתב "לא ידוע" עם הסיבה, ולעולם לא מנוחש.
"""
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)

GB = 1024 ** 3
LIMIT_GB = 9.0
FREE_TIER_GB = 10.0
UNKNOWN = "לא ידוע"


def row(label, value, width=34):
    print("  " + label.ljust(width) + str(value))


def head(title):
    print()
    print(title)
    print("  " + "-" * 56)


def fmt_gb(n):
    return f"{n / GB:.2f} GB"


# ------------------------------------------------------------------ ענן
def cloud_section():
    head("ענן (Cloudflare R2)")
    try:
        import upload_r2
    except Exception as exc:  # noqa: BLE001
        row("מצב", f"{UNKNOWN} - לא הצלחתי לטעון את upload_r2: {exc}")
        return None, None
    cfg = upload_r2.load_config()
    if not cfg:
        row("מצב", f"{UNKNOWN} - חסר cloud/r2_config.json, אי אפשר לבדוק את הענן.")
        return None, None
    try:
        objs, used = upload_r2.bucket_usage(cfg)
        n_open, open_bytes = upload_r2.open_multipart_bytes(cfg)
    except Exception as exc:  # noqa: BLE001
        row("מצב", f"{UNKNOWN} - הפנייה לדלי נכשלה: {exc}")
        return None, None

    for k, z in sorted(objs):
        row(k, fmt_gb(z))
    if not objs:
        row("הדלי ריק", "")
    total = used + open_bytes
    if n_open:
        row("העלאות שנקטעו", f"{n_open}, תופסות {fmt_gb(open_bytes)}")
        row("", "כדאי להריץ עדכון - הן מתבטלות אוטומטית בתחילתו")
    else:
        row("העלאות שנקטעו", "אין")
    row('סה"כ בשימוש', f"{fmt_gb(total)}  ({total / GB / FREE_TIER_GB * 100:.0f}% מהמכסה החינמית)")
    row("הגבול שהוגדר", f"{LIMIT_GB:.2f} GB")
    row("מרווח להעלאה הבאה", f"{(LIMIT_GB * GB - total) / GB:.2f} GB")
    return cfg, objs


# ------------------------------------------------------------------ האתר
def site_section(cfg, objs):
    head("האתר")
    cfg_js = os.path.join(REPO_DIR, "site", "config.js")
    try:
        text = io.open(cfg_js, encoding="utf-8").read()
    except OSError:
        row("מצב", f"{UNKNOWN} - לא נמצא site/config.js")
        return
    m = re.search(r'dbUrl:\s*"([^"]+)"', text)
    if not m:
        row("מצב", f"{UNKNOWN} - לא נמצאה שורת dbUrl ב-config.js")
        return
    key = m.group(1).rstrip("/").split("/")[-1]
    row("מצביע כרגע על", key)
    if objs is None:
        row("קיים בדלי", f"{UNKNOWN} - לא נבדק הענן")
        return
    exists = any(k == key for k, _z in objs)
    row("הקובץ קיים בדלי", "כן" if exists else "לא - האתר שבור!")
    if not exists:
        row("", "צריך להריץ עדכון, או להחזיר את config.js לגרסה קודמת")


# ------------------------------------------------------------------ מקומי
def local_section():
    head("מקומי")
    db = os.path.join(REPO_DIR, "prices.db")
    if os.path.exists(db):
        row("prices.db", fmt_gb(os.path.getsize(db)))
    else:
        row("prices.db", f"{UNKNOWN} - הקובץ לא נמצא")
    free = shutil.disk_usage(REPO_DIR).free
    row("מקום פנוי בכונן", fmt_gb(free))

    # קצב הגידול: חציון ולא ממוצע. ביום שבו סניף נראה לראשונה נכתבת לו
    # תמונת בסיס שלמה, ויום אחד כזה (10.7 מיליון רשומות ב-03.09) מזיז ממוצע
    # של שבוע פי חמישה. החציון מתעלם ממנו ומשקף יום רגיל.
    rows_per_day = None
    if os.path.exists(db):
        try:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            n, lo, hi = c.execute(
                "SELECT COUNT(*), MIN(date), MAX(date) FROM price_history").fetchone()
            row("היסטוריית מחירים", f"{n:,} רשומות, {lo} עד {hi}")
            # שבעה ימים ולא ארבעה-עשר: הכיסוי הפך ארצי רק בתחילת ספטמבר 2026,
            # וימים מלפני כן משקפים מעט רשתות ומושכים את החציון כלפי מטה.
            daily = [r[0] for r in c.execute(
                "SELECT COUNT(*) FROM price_history GROUP BY date "
                "ORDER BY date DESC LIMIT 7")]
            if daily:
                d = sorted(daily)
                rows_per_day = d[len(d) // 2]
                row("קצב גידול", f"כ-{rows_per_day:,} רשומות ביום (חציון של 7 הימים האחרונים)")
        except Exception as exc:  # noqa: BLE001
            row("היסטוריית מחירים", f"{UNKNOWN} - {exc}")

    # גידול הקובץ עצמו נמדד בין ריצות, ולא מוערך מכפל רשומות בבתים.
    hist_path = os.path.join(BASE_DIR, "size_history.json")
    samples = []
    try:
        samples = json.loads(io.open(hist_path, encoding="utf-8").read())
    except Exception:  # noqa: BLE001
        samples = []
    if len(samples) >= 2:
        first, last = samples[0], samples[-1]
        days = (last["t"] - first["t"]) / 86400.0
        grew = last["bytes"] - first["bytes"]
        if days >= 1 and grew > 0:
            per_day_bytes = grew / days
            row("גידול הקובץ בפועל", f"כ-{per_day_bytes / 1e6:.0f} מגה ליום "
                                     f"(נמדד על פני {days:.0f} ימים)")
            row("כלומר", f"כ-{per_day_bytes * 365 / GB:.0f} GB בשנה")
            years = free / (per_day_bytes * 365)
            row("לפי המקום הפנוי", f"מספיק לעוד כ-{years:.1f} שנים")
        else:
            row("גידול הקובץ בפועל", f"{UNKNOWN} - עדיין אין מספיק מרחק בין המדידות")
    else:
        row("גידול הקובץ בפועל", f"{UNKNOWN} - יימדד אחרי כמה ריצות יומיות")
    if free / GB < 25:
        row("", "המקום מתחיל להיגמר. אפשר לפנות מקום או להעביר היסטוריה ישנה.")

    dumps = os.path.join(REPO_DIR, "dumps")
    stuck = 0
    if os.path.isdir(dumps):
        cutoff = time.time() - 2 * 86400
        for r, _d, files in os.walk(dumps):
            if os.path.basename(r) == "status":
                continue
            for f in files:
                p = os.path.join(r, f)
                try:
                    if os.path.getmtime(p) < cutoff:
                        stuck += 1
                except OSError:
                    pass
    row("קבצים תקועים ב-dumps", stuck if stuck else "אין")
    if stuck:
        row("", "אלה קבצים שלא ניתן לפרסר, והם נשמרים וננסים שוב בכל ריצה")


# ------------------------------------------------------------------ ריצה אחרונה
def last_run_section():
    head("הריצה האחרונה")
    p = os.path.join(BASE_DIR, "last_run.json")
    if not os.path.exists(p):
        row("מצב", f"{UNKNOWN} - עוד לא רצה ריצה יומית")
        return
    try:
        d = json.loads(io.open(p, encoding="utf-8").read())
    except Exception as exc:  # noqa: BLE001
        row("מצב", f"{UNKNOWN} - {p} לא קריא: {exc}")
        return
    row("הסתיימה", d.get("finished") or UNKNOWN)
    row("תוצאה", "הצליחה" if d.get("ok") else f"נכשלה בשלב: {d.get('stage')}")
    if d.get("message"):
        row("", d["message"])
    if d.get("key"):
        row("הקובץ שעלה", d["key"])


def main():
    print()
    print("  מחירון - מצב המערכת".ljust(40) + time.strftime("%d/%m/%Y %H:%M"))
    cfg, objs = cloud_section()
    site_section(cfg, objs)
    local_section()
    last_run_section()
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
