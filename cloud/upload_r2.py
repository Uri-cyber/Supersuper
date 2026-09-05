# -*- coding: utf-8 -*-
"""
מעלה את מסד הנתונים ל-Cloudflare R2.

משתמש ב-API התואם-S3 של R2, עם חתימה מסוג SigV4 שמחושבת כאן מאפס.
אין צורך להתקין שום ספרייה חיצונית.

ההעלאה מפוצלת לחלקים של 64 מגה. אם החיבור נופל באמצע, אפשר להריץ שוב
ולהמשיך במקום להתחיל מהתחלה.

הגדרות: קובץ r2_config.json בתיקייה הזו (או משתני סביבה R2_*):
{
  "account_id":        "...",
  "access_key_id":     "...",
  "secret_access_key": "...",
  "bucket":            "mehiron"
}
הקובץ הזה לא נכנס לגיט. אל תשתפו אותו.

הרצה:  python upload_r2.py [--file mehiron-4096.db] [--key mehiron.db]
"""
import argparse
import calendar
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "r2_config.json")
STATE_PATH = os.path.join(BASE_DIR, ".upload_state.json")
PART_SIZE = 64 * 1024 * 1024
REGION = "auto"
SERVICE = "s3"


def log(msg):
    print(msg, flush=True)


def human(n):
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def db_version(path):
    """
    מזהה גרסה לקובץ המסד: התאריך האחרון שבנתונים ועוד חתימה קצרה של הגודל
    וזמן הבנייה. מספיק כדי ששני מסדים שונים לעולם לא יקבלו את אותו שם.
    """
    latest = ""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = conn.execute("SELECT value FROM app_meta WHERE key='latest_date'").fetchone()
        conn.close()
        if row:
            latest = str(row[0]).replace("-", "")
    except Exception:  # noqa: BLE001
        pass
    stamp = f"{os.path.getsize(path)}-{int(os.path.getmtime(path))}"
    short = hashlib.sha256(stamp.encode()).hexdigest()[:8]
    return f"{latest}-{short}" if latest else short


def update_site_config(url):
    """מעדכן את site/config.js לכתובת החדשה, כדי שהאתר יצביע על הגרסה הנכונה."""
    cfg_path = os.path.join(os.path.dirname(BASE_DIR), "site", "config.js")
    if not os.path.exists(cfg_path):
        log(f"לא נמצא {cfg_path}, לא עודכן.")
        return False
    text = io.open(cfg_path, encoding="utf-8").read()
    new_text = re.sub(r'(\n\s*dbUrl:\s*")[^"]*(")', lambda m: m.group(1) + url + m.group(2), text, count=1)
    if new_text == text:
        log("לא נמצאה שורת dbUrl לעדכון.")
        return False
    # כתיבה לקובץ זמני והחלפה אטומית. קריסה באמצע כתיבה רגילה משאירה
    # config.js קטוע, והאתר עולה ריק בלי שום דרך להבין למה.
    tmp = cfg_path + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(new_text)
    os.replace(tmp, cfg_path)
    log("עודכן site/config.js")
    return True


def _list_objects(cfg, prefix=None):
    """
    כל האובייקטים בדלי: [(key, size, last_modified)].

    R2 מחזירה את השדות בסדר Key, Size, LastModified, אבל לא מסתמכים על כך -
    כל אובייקט נחתך בנפרד ורק אז נשלפים ממנו השדות. יש גם לולאת המשך, כי
    בקשה אחת מחזירה 1000 מפתחות לכל היותר.
    """
    out, token = [], None
    while True:
        params = [("list-type", 2)]
        if prefix:
            params.append(("prefix", prefix))
        if token:
            params.append(("continuation-token", token))
        body = signed_request(cfg, "GET", "", params=params).read().decode("utf-8", "replace")
        for block in re.findall(r"<Contents>(.*?)</Contents>", body, re.S):
            k = re.search(r"<Key>([^<]+)</Key>", block)
            z = re.search(r"<Size>(\d+)</Size>", block)
            t = re.search(r"<LastModified>([^<]+)</LastModified>", block)
            if k:
                out.append((k.group(1), int(z.group(1)) if z else 0, t.group(1) if t else ""))
        if "<IsTruncated>true</IsTruncated>" not in body:
            break
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", body)
        if not m:
            break
        token = m.group(1)
    return out


def list_db_objects(cfg):
    """
    קובצי המסד בלבד, לפי ותק. הסינון לפי התחילית מכוון: הניקוי לא אמור
    לגעת בשום דבר אחר שנמצא בדלי. בדיקת המכסה, לעומת זאת, סופרת הכול.
    """
    objs = [(k, t) for k, _z, t in _list_objects(cfg, prefix="mehiron-")]
    return sorted(objs, key=lambda x: x[1])


GB = 1024 ** 3


def bucket_usage(cfg):
    """
    כל האובייקטים בדלי עם הגודל שלהם: [(key, size)], וגם הסכום.
    בלי סינון תחילית - גם קובץ זר תופס מהמכסה החינמית.
    """
    out = [(k, z) for k, z, _t in _list_objects(cfg)]
    return out, sum(z for _k, z in out)


def list_multipart_uploads(cfg):
    """כל ההעלאות הפתוחות בדלי: [(key, upload_id, initiated)]."""
    out, kmark, umark = [], None, None
    while True:
        params = [("uploads", "")]
        if kmark:
            params.append(("key-marker", kmark))
        if umark:
            params.append(("upload-id-marker", umark))
        body = signed_request(cfg, "GET", "", params=params).read().decode("utf-8", "replace")
        for block in re.findall(r"<Upload>(.*?)</Upload>", body, re.S):
            k = re.search(r"<Key>([^<]+)</Key>", block)
            u = re.search(r"<UploadId>([^<]+)</UploadId>", block)
            i = re.search(r"<Initiated>([^<]+)</Initiated>", block)
            if k and u:
                out.append((k.group(1), u.group(1), i.group(1) if i else ""))
        if "<IsTruncated>true</IsTruncated>" not in body:
            break
        km = re.search(r"<NextKeyMarker>([^<]*)</NextKeyMarker>", body)
        um = re.search(r"<NextUploadIdMarker>([^<]*)</NextUploadIdMarker>", body)
        if not (km and um):
            break
        kmark, umark = km.group(1), um.group(1)
    return out


def upload_parts_bytes(cfg, key, upload_id):
    """סכום גודל החלקים שכבר הועלו בהעלאה פתוחה אחת."""
    try:
        pb = signed_request(cfg, "GET", key,
                            params=[("uploadId", upload_id)]).read().decode("utf-8", "replace")
        return sum(int(x) for x in re.findall(r"<Size>(\d+)</Size>", pb))
    except Exception:  # noqa: BLE001
        return 0


def open_multipart_bytes(cfg):
    """
    חלקים של העלאות שנקטעו. הם נספרים באחסון עד שמבטלים אותן, ולכן דלי
    שנראה תקין ברשימת הקבצים יכול בכל זאת להיות מלא.
    """
    ups = list_multipart_uploads(cfg)
    return len(ups), sum(upload_parts_bytes(cfg, k, u) for k, u, _t in ups)


def abort_orphan_uploads(cfg, protect_key=None, min_age_hours=2):
    """
    מבטל העלאות שנקטעו ושוכבות בדלי.

    ל-R2 יש כלל ברירת מחדל שמבטל אותן אחרי שבעה ימים, אבל עד אז כל ניסיון
    שנכשל תופס עד שני ג'יגה - ובינתיים בדיקת המכסה תחסום את ההעלאה של מחר.

    ההגנה היא לפי מפתח ולא לפי מזהה העלאה, וזה לא עניין של נוחות: נמדד ש-R2
    מחזירה UploadId שונה בכל קריאה ל-ListMultipartUploads עבור אותה העלאה
    עצמה. שלוש קריאות רצופות החזירו שלושה מזהים שונים. לכן השוואת מזהה
    לזה ששמור אצלנו על הדיסק תיכשל תמיד, וההגנה הייתה מבטלת דווקא את
    ההעלאה שאנחנו באמצע המשכתה.

    המזהה שמשמש לביטול נלקח מאותה תשובת רשימה עצמה, ולכן הוא תקף.
    """
    freed, n = 0, 0
    now = time.time()
    for key, upload_id, initiated in list_multipart_uploads(cfg):
        if protect_key and key == protect_key:
            continue
        age_h = None
        if initiated:
            try:
                ts = calendar.timegm(time.strptime(initiated[:19], "%Y-%m-%dT%H:%M:%S"))
                age_h = (now - ts) / 3600.0
            except ValueError:
                age_h = None
        # העלאה שנפתחה זה עתה עשויה להיות ריצה ידנית שרצה במקביל בחלון אחר
        if age_h is not None and age_h < min_age_hours:
            continue
        size = upload_parts_bytes(cfg, key, upload_id)
        try:
            signed_request(cfg, "DELETE", key, params=[("uploadId", upload_id)])
            freed += size
            n += 1
        except Exception as exc:  # noqa: BLE001
            log(f"  לא הצלחתי לבטל העלאה תקועה של {key}: {exc}")
    if n:
        log(f"בוטלו {n} העלאות שנקטעו ופינו {freed / GB:.2f} GB.")
    return n, freed


def verify_uploaded(cfg, key, expected_size):
    """
    בדיקה שהקובץ באמת נחת, לפני שמפנים אליו את האתר.

    CompleteMultipartUpload יכול להחזיר 200 ועדיין להיכשל בגוף התשובה, ולכן
    "לא נזרקה חריגה" אינו מספיק כדי לפרסם.
    """
    try:
        resp = signed_request(cfg, "HEAD", key)
    except Exception as exc:  # noqa: BLE001
        log(f"האובייקט לא נמצא בדלי אחרי ההעלאה: {exc}")
        return False
    got = int(resp.headers.get("Content-Length") or 0)
    if got != expected_size:
        log(f"גודל שונה בדלי: {got:,} במקום {expected_size:,} בתים.")
        return False
    log(f"אומת בדלי: {key} בגודל {got:,} בתים.")
    return True


def check_quota(cfg, incoming_bytes, limit_gb):
    """
    בודק לפני ההעלאה שהיא לא תחרוג מהגבול.

    בשיא ההעלאה קיימים בדלי גם הקובץ הישן וגם החדש, כי הניקוי מתרחש רק
    אחרי שההעלאה הצליחה. לכן החישוב הוא על השיא ולא על המצב הסופי.
    """
    objs, used = bucket_usage(cfg)
    n_open, open_bytes = open_multipart_bytes(cfg)
    peak = used + open_bytes + incoming_bytes
    log("")
    log("תפוסה בדלי %s:" % cfg["bucket"])
    for k, z in sorted(objs):
        log("  %-44s %5.2f GB" % (k, z / GB))
    if n_open:
        log("  (%d העלאות שנקטעו תופסות %.2f GB)" % (n_open, open_bytes / GB))
    log("  בשימוש כעת   %14s בתים = %.2f GB" % ("{:,}".format(used + open_bytes), (used + open_bytes) / GB))
    log("  הקובץ החדש   %14s בתים = %.2f GB" % ("{:,}".format(incoming_bytes), incoming_bytes / GB))
    log("  שיא צפוי     %14s בתים = %.2f GB   (גבול: %.2f GB)" % ("{:,}".format(peak), peak / GB, limit_gb))
    if peak > limit_gb * GB:
        log("")
        log("ההעלאה נעצרה: היא הייתה מביאה את הדלי ל-%.2f GB, מעל הגבול שהוגדר." % (peak / GB))
        log("אפשר למחוק גרסה ישנה בלוח הבקרה של R2, או להריץ שוב עם --max-gb גבוה יותר.")
        return False
    log("  נשאר מרווח של %.2f GB מתחת לגבול." % ((limit_gb * GB - peak) / GB))
    return True


def prune_old(cfg, keep_key, keep=1, protect_keys=()):
    """
    מוחק גרסאות ישנות, ומשאיר את החדשה ועוד אחת.

    הקודמת נשארת כדי שלקוח שכבר טעון על הגרסה הישנה לא ייפול באמצע שימוש.

    protect_keys הוא המפתח שהאתר החי מצביע עליו כרגע. בלעדיו, שתי דחיפות
    כושלות ברצף הופכות את המפתח החי לשלישי בוותק - כלומר לקורבן של הניקוי,
    והאתר מקבל 404 על המסד.
    """
    protect = set(protect_keys or ())
    objs = [k for k, _ts in list_db_objects(cfg) if k != keep_key and k not in protect]
    victims = objs[:-keep] if keep else objs
    for k in victims:
        try:
            signed_request(cfg, "DELETE", k)
            log(f"  נמחקה גרסה ישנה: {k}")
        except Exception as exc:  # noqa: BLE001
            log(f"  לא הצלחתי למחוק {k}: {exc}")
    if objs[-keep:] if keep else []:
        log(f"  נשמרה גרסה קודמת: {(objs[-keep:] if keep else [''])[0]}")


def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
    for key, env in [("account_id", "R2_ACCOUNT_ID"), ("access_key_id", "R2_ACCESS_KEY_ID"),
                     ("secret_access_key", "R2_SECRET_ACCESS_KEY"), ("bucket", "R2_BUCKET")]:
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    missing = [k for k in ("account_id", "access_key_id", "secret_access_key", "bucket")
               if not cfg.get(k)]
    if missing:
        log("חסרות הגדרות: " + ", ".join(missing))
        log(f"צרו את הקובץ {CONFIG_PATH} לפי הדוגמה שבתחילת הקובץ הזה.")
        return None
    return cfg


# ------------------------------------------------------------------ SigV4
def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret, datestamp):
    k = _sign(("AWS4" + secret).encode("utf-8"), datestamp)
    k = _sign(k, REGION)
    k = _sign(k, SERVICE)
    return _sign(k, "aws4_request")


def build_query(params):
    """
    בונה מחרוזת שאילתה אחת שמשמשת גם לכתובת וגם לחתימה.

    שתיהן חייבות להיות זהות לחלוטין: פרמטרים ממוינים לפי שם, וכל פרמטר
    בצורת שם=ערך גם כשאין לו ערך. אחרת R2 מחשבת חתימה אחרת ומחזירה
    SignatureDoesNotMatch, וזה מה שקרה עם "?uploads" שנחתם בלי סימן שוויון.
    """
    if not params:
        return ""
    pairs = sorted((urllib.parse.quote(str(k), safe="-_.~"),
                    urllib.parse.quote("" if v is None else str(v), safe="-_.~"))
                   for k, v in params)
    return "&".join(f"{k}={v}" for k, v in pairs)


def signed_request(cfg, method, key, params=None, payload=b"", body_len=None,
                   body_stream=None, content_sha=None, extra_headers=None):
    """בונה בקשה חתומה ל-R2 ומחזיר את התשובה."""
    host = f"{cfg['account_id']}.r2.cloudflarestorage.com"
    canonical_uri = "/" + cfg["bucket"] + "/" + key.lstrip("/")
    now = dt.datetime.now(dt.timezone.utc)
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    if content_sha is None:
        content_sha = hashlib.sha256(payload).hexdigest()
    length = body_len if body_len is not None else len(payload)

    headers = {
        "host": host,
        "x-amz-content-sha256": content_sha,
        "x-amz-date": amzdate,
    }
    for k, v in (extra_headers or {}).items():
        headers[k.lower()] = v

    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    query = build_query(params)
    canonical_request = "\n".join([method, canonical_uri, query,
                                   canonical_headers, signed_headers, content_sha])
    scope = f"{datestamp}/{REGION}/{SERVICE}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amzdate, scope,
                         hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()])
    signature = hmac.new(signing_key(cfg["secret_access_key"], datestamp),
                         to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={cfg['access_key_id']}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}")

    url = f"https://{host}{canonical_uri}" + (f"?{query}" if query else "")
    req = urllib.request.Request(url, method=method, data=body_stream or (payload or None))
    for k, v in headers.items():
        req.add_header(k, v)
    if method in ("PUT", "POST"):
        req.add_header("Content-Length", str(length))
    return urllib.request.urlopen(req, timeout=600)


class PartReader:
    """קורא חלק אחד מהקובץ, כדי שלא נטען 64 מגה לזיכרון בבת אחת."""

    def __init__(self, path, offset, size):
        self.fh = open(path, "rb")
        self.fh.seek(offset)
        self.left = size

    def read(self, n=-1):
        if self.left <= 0:
            return b""
        if n is None or n < 0:
            n = self.left
        data = self.fh.read(min(n, self.left))
        self.left -= len(data)
        return data

    def close(self):
        self.fh.close()


def part_sha256(path, offset, size):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        fh.seek(offset)
        left = size
        while left > 0:
            chunk = fh.read(min(1024 * 1024, left))
            if not chunk:
                break
            h.update(chunk)
            left -= len(chunk)
    return h.hexdigest()


def load_state(key, size, mtime):
    if not os.path.exists(STATE_PATH):
        return None
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            st = json.load(fh)
    except Exception:  # noqa: BLE001
        return None
    if st.get("key") == key and st.get("size") == size and st.get("mtime") == mtime:
        return st
    return None


def save_state(st):
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(st, fh)


def discard_state():
    """מוחק את מצב ההמשך. ריצה הבאה תתחיל העלאה נקייה."""
    try:
        os.remove(STATE_PATH)
    except OSError:
        pass


def state_key():
    """המפתח שמצב ההמשך שמור עבורו, אם יש כזה."""
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("key")
    except Exception:  # noqa: BLE001
        return None


def upload_id_alive(cfg, key, upload_id):
    """
    האם ההעלאה שאנחנו רוצים להמשיך עדיין קיימת בשרת.

    בלי הבדיקה הזו, מזהה שכבר בוטל גורם ל-404 בכל ריצה, הריצה נכשלת ולא
    מוחקת את קובץ המצב - וכך היא נכשלת באותה צורה לנצח.
    """
    try:
        signed_request(cfg, "GET", key, params=[("uploadId", upload_id), ("max-parts", 1)])
        return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def upload(cfg, path, key):
    size = os.path.getsize(path)
    mtime = int(os.path.getmtime(path))
    n_parts = (size + PART_SIZE - 1) // PART_SIZE
    log(f"מעלה {os.path.basename(path)} ({human(size)}) אל {cfg['bucket']}/{key}")
    log(f"{n_parts} חלקים של {PART_SIZE // 1024 // 1024} מגה")

    state = load_state(key, size, mtime)
    if state and not upload_id_alive(cfg, key, state["upload_id"]):
        log("ההעלאה הקודמת כבר לא קיימת בשרת. מוחק את מצב ההמשך ומתחיל מחדש.")
        discard_state()
        state = None
    if state:
        log(f"ממשיך העלאה קודמת: {len(state['parts'])} חלקים כבר הועלו")
        upload_id = state["upload_id"]
        done = {int(k): v for k, v in state["parts"].items()}
    else:
        resp = signed_request(cfg, "POST", key, params=[("uploads", "")],
                              extra_headers={
                                  "content-type": "application/octet-stream",
                                  # לכל גרסה שם משלה, ולכן מותר לשמור אותה במטמון לצמיתות.
                                  # בלי זה הדפדפן מערבב חתיכות משתי גרסאות והמסד נראה פגום.
                                  "cache-control": "public, max-age=31536000, immutable",
                              })
        root = ET.fromstring(resp.read())
        ns = {"s3": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
        upload_id = root.find("s3:UploadId", ns).text if ns else root.find("UploadId").text
        done = {}
        state = {"key": key, "size": size, "mtime": mtime, "upload_id": upload_id, "parts": {}}
        save_state(state)
    log(f"מזהה העלאה: {upload_id[:20]}…")

    t0 = time.time()
    uploaded = sum(PART_SIZE for i in done if i < n_parts)
    for i in range(1, n_parts + 1):
        if i in done:
            continue
        offset = (i - 1) * PART_SIZE
        plen = min(PART_SIZE, size - offset)
        sha = part_sha256(path, offset, plen)
        reader = PartReader(path, offset, plen)
        try:
            resp = signed_request(cfg, "PUT", key,
                                  params=[("partNumber", i), ("uploadId", upload_id)],
                                  body_len=plen, body_stream=reader, content_sha=sha)
            etag = resp.headers.get("ETag", "").strip('"')
        finally:
            reader.close()
        done[i] = etag
        state["parts"][str(i)] = etag
        save_state(state)
        uploaded += plen
        rate = uploaded / max(0.1, time.time() - t0)
        left = (size - uploaded) / max(1, rate)
        log(f"  חלק {i}/{n_parts} · {uploaded * 100 // size}% · "
            f"{rate / 1e6:.1f} MB/s · נותרו כ-{int(left // 60)} דק'")

    parts_xml = "".join(
        f"<Part><PartNumber>{i}</PartNumber><ETag>\"{done[i]}\"</ETag></Part>"
        for i in sorted(done))
    body = f"<CompleteMultipartUpload>{parts_xml}</CompleteMultipartUpload>".encode("utf-8")
    signed_request(cfg, "POST", key, params=[("uploadId", upload_id)], payload=body,
                   extra_headers={"content-type": "application/xml"})
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
    log(f"\nההעלאה הושלמה ב-{int((time.time() - t0) // 60)} דק'.")
    log(f"הקובץ זמין בדלי {cfg['bucket']} תחת השם {key}.")


def main():
    ap = argparse.ArgumentParser(description="העלאת מסד מחירון ל-Cloudflare R2")
    ap.add_argument("--file", default=os.path.join(BASE_DIR, "mehiron-16384.db"))
    ap.add_argument("--key", default=None,
                    help="שם הקובץ בדלי. ברירת מחדל: שם עם גרסה, שנגזר מהנתונים")
    ap.add_argument("--public-base", default=None,
                    help="הכתובת הציבורית של הדלי, לעדכון אוטומטי של site/config.js")
    ap.add_argument("--no-prune", action="store_true", help="לא למחוק גרסאות ישנות")
    ap.add_argument("--no-abort-orphans", action="store_true",
                    help="לא לבטל העלאות שנקטעו לפני ההעלאה")
    ap.add_argument("--protect-key", default=None,
                    help="מפתח שאסור למחוק בניקוי - זה שהאתר החי מצביע עליו")
    ap.add_argument("--max-gb", type=float, default=9.0,
                    help="גבול תפוסה בדלי בג'יגה. ההעלאה נעצרת אם השיא יחרוג ממנו")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        log(f"לא נמצא {args.file}. הריצו קודם: python build_cloud_db.py --page-size 4096")
        return 1
    cfg = load_config()
    if not cfg:
        return 1
    key = args.key or f"mehiron-{db_version(args.file)}.db"
    base = args.public_base or cfg.get("public_base")
    try:
        # קודם מפנים חלקים של העלאות שנקטעו, ורק אז מודדים - כדי שהמקום
        # שהתפנה ייספר לטובת ההעלאה הנוכחית.
        if not args.no_abort_orphans:
            # מגנים על המפתח הנוכחי רק אם באמת יש לנו מצב המשך עבורו
            resuming = state_key() == key
            abort_orphan_uploads(cfg, protect_key=key if resuming else None)
        if not check_quota(cfg, os.path.getsize(args.file), args.max_gb):
            return 1
        upload(cfg, args.file, key)
        # אין מפרסמים קובץ שלא אומת. זו ההגנה שמונעת אתר שמצביע על כלום.
        if not verify_uploaded(cfg, key, os.path.getsize(args.file)):
            log("\nההעלאה לא אומתה. site/config.js לא עודכן, והאתר ממשיך על הגרסה הקודמת.")
            return 1
        if base:
            update_site_config(base.rstrip("/") + "/" + key)
        else:
            log("\nלא הוגדרה public_base, לכן site/config.js לא עודכן.")
            log(f"עדכנו ידנית את dbUrl לשם הקובץ: {key}")
        if not args.no_prune:
            log("\nמנקה גרסאות ישנות בדלי:")
            prune_old(cfg, key, keep=1,
                      protect_keys=[args.protect_key] if args.protect_key else ())
        _objs, after = bucket_usage(cfg)
        log("")
        log("תפוסה סופית: %.2f GB מתוך גבול של %.2f GB (המכסה החינמית היא 10 GB)."
            % (after / GB, args.max_gb))
    except urllib.error.HTTPError as e:
        log(f"\nשגיאה מהשרת: {e.code} {e.reason}")
        body = e.read().decode("utf-8", "replace")[:600]
        if body:
            log(body)
        if "NoSuchUpload" in body:
            # גם אם הגענו לכאן בדרך שלא צפינו, לא משאירים מצב שיכשיל לנצח
            discard_state()
            log("מצב ההמשך נמחק. הריצה הבאה תתחיל העלאה נקייה.")
        log("\nבדקו את המפתחות ואת שם הדלי ב-r2_config.json.")
        return 1
    except urllib.error.URLError as e:
        log(f"\nשגיאת רשת: {e.reason}. אפשר להריץ שוב וההעלאה תמשיך מהמקום שנעצרה.")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
