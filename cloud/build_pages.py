# -*- coding: utf-8 -*-
"""
עמודים סטטיים למוצרים הנפוצים, כדי שמנועי חיפוש ימצאו אותם.

האתר עצמו נבנה בדפדפן מתוך קובץ הנתונים, ולכן גוגל רואה בו עמוד אחד.
כאן נוצר קובץ HTML רגיל לכל אחד מאלף המוצרים שנמכרים בהכי הרבה סניפים,
עם המחירים שפורסמו, התאריך של כל מחיר, ומפת אתר שמפנה אליהם.

החישובים נעשים דרך הפונקציות של app/server.py, כדי שהמספרים יהיו זהים
למה שהאתר מציג. מוצר שנפסל במסנן החריגים של כותרות עמוד הבית (מחיר
נמוך או גבוה מדי ביחס לחציון, פער תאריכים) לא מקבל עמוד: עמוד שגוגל
מציג צריך להיות מספר שאפשר להגן עליו.

    python cloud/build_pages.py [--limit 1000]

הפלט: site/p/<ברקוד>.html, site/p/index.html, site/sitemap.xml,
ו-cloud/pages_built.json עם תאריך הבנייה.
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(BASE, "site")
OUT = os.path.join(SITE, "p")
STAMP = os.path.join(BASE, "cloud", "pages_built.json")
ORIGIN = "https://mehiron.app"

sys.path.insert(0, os.path.join(BASE, "app"))
import server as srv  # noqa: E402


def log(msg=""):
    print(msg, flush=True)


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def pretty(name):
    """כמו prettyName באתר: רווח בין אות עברית לספרה, לתצוגה בלבד."""
    s = "" if name is None else str(name)
    s = re.sub(r"([֐-׿])(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)([֐-׿])", r"\1 \2", s)
    return s


def nis(v):
    return f"{v:,.2f}"


def date_he(d):
    try:
        return dt.date.fromisoformat(d).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return "לא ידוע"


def pick_products(limit):
    out, skipped = [], 0
    for row in srv.q(
        """
        SELECT * FROM product_stats
        WHERE name IS NOT NULL AND name <> '' AND n_stores >= 30
        ORDER BY n_stores DESC, barcode
        """
    ):
        b = srv.product_brief(row)
        if srv._headline_reject(b):
            skipped += 1
            continue
        out.append((row, b))
        if len(out) >= limit:
            break
    return out, skipped


def chain_rows(barcode, cutoff):
    """הזול ביותר בכל רשת בחלון הטריות, עם הסניף והתאריך שלו."""
    best = {}
    for r in srv.q(
        "SELECT chain, store_id, price, date FROM prices WHERE barcode = ? AND date >= ?",
        (barcode, cutoff),
    ):
        cur = best.get(r["chain"])
        if cur is None or r["price"] < cur["price"] or (
                r["price"] == cur["price"] and r["date"] > cur["date"]):
            best[r["chain"]] = dict(r)
    rows = []
    for ch, r in best.items():
        m = srv.store_meta(ch, r["store_id"])
        rows.append({"chain": ch, "price": srv.money(r["price"]), "date": r["date"], **m})
    rows.sort(key=lambda x: (x["price"], x["chain"]))
    return rows


def store_line(meta):
    city = meta.get("city") or srv.UNKNOWN
    branch = meta.get("branch") or srv.UNKNOWN
    s = esc(branch)
    if city and city != branch:
        s += ", " + esc(city)
    return s


def head(title, desc, path, extra=""):
    url = ORIGIN + path
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="מחירון">
<meta property="og:locale" content="he_IL">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:image" content="{ORIGIN}/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#14151a">
<link rel="icon" href="/icon-192.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="stylesheet" href="/p/page.css">
{extra}</head>
<body>
<a class="skip" href="#main">דילוג לתוכן</a>
<header><div class="wrap"><a class="brand" href="/">₪ מחירון</a>
<a class="back" href="/p/">כל המוצרים</a></div></header>
<main id="main" class="wrap">
"""


FOOT = """</main>
<footer class="wrap foot">
<p>המחירים לפי הקבצים שהרשתות מפרסמות בהתאם לחוק קידום התחרות בענף המזון. ייתכנו טעויות ואין להסתמך עליהם כמחיר בקופה.</p>
<nav aria-label="מידע משפטי"><a href="/legal#terms">תנאי שימוש</a> · <a href="/legal#privacy">פרטיות</a> · <a href="/legal#accessibility">נגישות</a> · <a href="/legal#report">דיווח על טעות</a></nav>
</footer>
<script src="/host.js"></script>
</body>
</html>
"""


def product_page(row, b, latest, built):
    code = b["barcode"]
    name = pretty(b["name"])
    cutoff = srv.fresh_cutoff()
    chains = chain_rows(code, cutoff)
    lo = srv.store_meta(b["min_chain"], row["min_store"])
    hi = srv.store_meta(b["max_chain"], row["max_store"])

    title = f"{name} - מחיר ב־{b['stores']:,} סניפים | מחירון"
    desc = (f"המחיר של {name} ב־{b['chains']} רשתות: מ־{nis(b['min'])} ₪ עד {nis(b['max'])} ₪, "
            f"חציון {nis(b['median'])} ₪. לפי הקבצים שהרשתות פרסמו עד {date_he(latest)}.")

    ld = {
        "@context": "https://schema.org", "@type": "Product", "name": b["name"],
        "url": f"{ORIGIN}/p/{code}",
        "offers": {"@type": "AggregateOffer", "priceCurrency": "ILS",
                   "lowPrice": f"{b['min']:.2f}", "highPrice": f"{b['max']:.2f}",
                   "offerCount": b["stores"]},
    }
    if code.isdigit() and len(code) in (8, 12, 13, 14):
        ld["gtin" + str(len(code))] = code
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    extra = f'<script type="application/ld+json">{ld_json}</script>\n'

    rows = "".join(
        f"<tr><td>{esc(c['chain'])}</td><td>{store_line(c)}</td>"
        f"<td class=\"num\">{nis(c['price'])} ₪</td><td>{date_he(c['date'])}</td></tr>\n"
        for c in chains)

    body = f"""<p class="kicker">נמכר ב־{b['stores']:,} סניפים של {b['chains']} רשתות · ברקוד {esc(code)}</p>
<h1>{esc(name)}</h1>
<div class="cards">
  <div class="card lo"><div class="lbl">הנמוך ביותר שפורסם</div><div class="val">{nis(b['min'])} ₪</div>
    <div class="sub">{esc(b['min_chain'])} · {store_line(lo)}</div><div class="sub">פורסם ב־{date_he(b['min_date'])}</div></div>
  <div class="card"><div class="lbl">החציון הארצי</div><div class="val">{nis(b['median'])} ₪</div>
    <div class="sub">מ־{b['stores']:,} סניפים</div></div>
  <div class="card hi"><div class="lbl">הגבוה ביותר שפורסם</div><div class="val">{nis(b['max'])} ₪</div>
    <div class="sub">{esc(b['max_chain'])} · {store_line(hi)}</div><div class="sub">פורסם ב־{date_he(b['max_date'])}</div></div>
</div>
<p><a class="cta" href="/#product/{esc(code)}">לכל הסניפים, לגרף המחיר ולסינון לפי עיר</a></p>
<h2>המחיר הזול ביותר בכל רשת</h2>
<div class="scroll"><table>
<caption>הסניף הזול ביותר בכל רשת, לפי הקבצים מ־{date_he(cutoff)} ואילך</caption>
<thead><tr><th scope="col">רשת</th><th scope="col">סניף</th><th scope="col">מחיר</th><th scope="col">תאריך פרסום</th></tr></thead>
<tbody>
{rows}</tbody></table></div>
<p class="note">סניף שהרשת שלו לא פרסמה את שמו או את העיר מופיע כ"לא ידוע". העמוד עודכן ב־{date_he(built)}; המחירים המעודכנים ביותר נמצאים באתר עצמו.</p>
"""
    return head(title, desc, f"/p/{code}", extra) + body + FOOT


def index_page(items, latest, built):
    lis = "".join(
        f'<li><a href="/p/{esc(b["barcode"])}">{esc(pretty(b["name"]))}</a> '
        f'<span class="muted">· {b["stores"]:,} סניפים · מ־{nis(b["min"])} ₪</span></li>\n'
        for _r, b in sorted(items, key=lambda x: pretty(x[1]["name"])))
    title = "מחירי מוצרים נפוצים בסופרמרקטים | מחירון"
    desc = (f"{len(items):,} המוצרים שנמכרים בהכי הרבה סניפים בישראל, עם המחיר הזול והיקר ביותר שפורסם "
            f"ותאריך הפרסום. לפי הקבצים שהרשתות פרסמו עד {date_he(latest)}.")
    body = f"""<h1>מחירי מוצרים נפוצים</h1>
<p>{len(items):,} המוצרים שנמכרים בהכי הרבה סניפים, מסודרים לפי שם. לכל מוצר יש עמוד עם המחיר הזול והיקר
ביותר שפורסם, החציון הארצי והמחיר בכל רשת. לחיפוש כל מוצר אחר: <a href="/">בעמוד הבית</a>.</p>
<p class="note">הרשימה עודכנה ב־{date_he(built)}.</p>
<ul class="plist">
{lis}</ul>
"""
    return head(title, desc, "/p/") + body + FOOT


def sitemap(items, latest):
    urls = [(f"{ORIGIN}/", latest), (f"{ORIGIN}/legal", latest), (f"{ORIGIN}/p/", latest)]
    urls += [(f"{ORIGIN}/p/{b['barcode']}", latest) for _r, b in items]
    body = "".join(f"  <url><loc>{esc(u)}</loc><lastmod>{d}</lastmod></url>\n" for u, d in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "</urlset>\n")


def write(path, text):
    """כותב רק אם התוכן השתנה, כדי שגיט לא יראה שינוי ריק."""
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == text:
                return False
    except OSError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    args = ap.parse_args()
    t0 = time.time()
    latest = srv.latest_data_date()
    built = dt.date.today().isoformat()
    items, skipped = pick_products(args.limit)
    log(f"{len(items):,} מוצרים נבחרו, {skipped:,} נפסלו במסנן החריגים")

    os.makedirs(OUT, exist_ok=True)
    keep, changed = set(), 0
    for i, (row, b) in enumerate(items, 1):
        fn = f"{b['barcode']}.html"
        keep.add(fn)
        changed += write(os.path.join(OUT, fn), product_page(row, b, latest, built))
        if i % 200 == 0:
            log(f"    {i:,} עמודים, {round(time.time() - t0)} שניות")
    keep.add("index.html")
    changed += write(os.path.join(OUT, "index.html"), index_page(items, latest, built))
    # מוצר שיצא מהרשימה: העמוד שלו נמחק, כדי שגוגל לא יציג מחיר ישן
    removed = 0
    for fn in os.listdir(OUT):
        if fn.endswith(".html") and fn not in keep:
            os.remove(os.path.join(OUT, fn))
            removed += 1
    write(os.path.join(SITE, "sitemap.xml"), sitemap(items, latest))
    with open(STAMP, "w", encoding="utf-8") as fh:
        json.dump({"built": built, "latest": latest, "pages": len(items)}, fh)
    log(f"עודכנו {changed:,} עמודים, נמחקו {removed:,}, {round(time.time() - t0)} שניות")
    return 0


if __name__ == "__main__":
    sys.exit(main())
