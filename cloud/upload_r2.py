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
import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
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


def signed_request(cfg, method, key, query="", payload=b"", body_len=None,
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
    canonical_request = "\n".join([method, canonical_uri, query, canonical_headers,
                                   signed_headers, content_sha])
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


def upload(cfg, path, key):
    size = os.path.getsize(path)
    mtime = int(os.path.getmtime(path))
    n_parts = (size + PART_SIZE - 1) // PART_SIZE
    log(f"מעלה {os.path.basename(path)} ({human(size)}) אל {cfg['bucket']}/{key}")
    log(f"{n_parts} חלקים של {PART_SIZE // 1024 // 1024} מגה")

    state = load_state(key, size, mtime)
    if state:
        log(f"ממשיך העלאה קודמת: {len(state['parts'])} חלקים כבר הועלו")
        upload_id = state["upload_id"]
        done = {int(k): v for k, v in state["parts"].items()}
    else:
        resp = signed_request(cfg, "POST", key, query="uploads",
                              extra_headers={"content-type": "application/octet-stream"})
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
                                  query=f"partNumber={i}&uploadId={upload_id}",
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
    signed_request(cfg, "POST", key, query=f"uploadId={upload_id}", payload=body,
                   extra_headers={"content-type": "application/xml"})
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
    log(f"\nההעלאה הושלמה ב-{int((time.time() - t0) // 60)} דק'.")
    log(f"הקובץ זמין בדלי {cfg['bucket']} תחת השם {key}.")


def main():
    ap = argparse.ArgumentParser(description="העלאת מסד מחירון ל-Cloudflare R2")
    ap.add_argument("--file", default=os.path.join(BASE_DIR, "mehiron-4096.db"))
    ap.add_argument("--key", default="mehiron.db")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        log(f"לא נמצא {args.file}. הריצו קודם: python build_cloud_db.py --page-size 4096")
        return 1
    cfg = load_config()
    if not cfg:
        return 1
    try:
        upload(cfg, args.file, args.key)
    except urllib.error.HTTPError as e:
        log(f"\nשגיאה מהשרת: {e.code} {e.reason}")
        body = e.read().decode("utf-8", "replace")[:600]
        if body:
            log(body)
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
