# -*- coding: utf-8 -*-
"""
שרת סטטי מקומי עם תמיכה בבקשות HTTP Range, שמדמה את מה ש-Cloudflare R2 נותנת.

SimpleHTTPRequestHandler של פייתון לא תומך ב-Range, ובלי זה הדפדפן היה מוריד
את כל המסד. השרת הזה גם סופר כמה בקשות וכמה בתים נשלחו, וזה בדיוק מה שאנחנו
רוצים למדוד: כמה תעבורה עולה עמוד מוצר אחד.

הרצה:  python range_server.py [--port 8777]
מונים: GET /__stats  |  איפוס: GET /__stats/reset
"""
import argparse
import json
import mimetypes
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")

_lock = threading.Lock()
STATS = {"requests": 0, "range_requests": 0, "bytes": 0, "by_file": {}}
# השהיה מדומה לכל בקשה, כדי למדוד איך זה יתנהג באינטרנט אמיתי ולא על localhost
DELAY_MS = 0.0


def bump(path, nbytes, is_range):
    with _lock:
        STATS["requests"] += 1
        STATS["bytes"] += nbytes
        if is_range:
            STATS["range_requests"] += 1
        f = STATS["by_file"].setdefault(path, {"requests": 0, "bytes": 0})
        f["requests"] += 1
        f["bytes"] += nbytes


class Handler(BaseHTTPRequestHandler):
    server_version = "RangeTest"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        # אותן כותרות ש-R2 מחזירה לדלי ציבורי
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Range")
        self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges")
        self.send_header("Accept-Ranges", "bytes")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):  # noqa: N802
        self._serve(head_only=True)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/__stats"):
            if self.path.endswith("/reset"):
                with _lock:
                    STATS.update(requests=0, range_requests=0, bytes=0, by_file={})
            body = json.dumps(STATS, ensure_ascii=False).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._serve()

    def _serve(self, head_only=False):
        rel = self.path.split("?", 1)[0].lstrip("/")
        if not rel:
            rel = "test.html"
        target = os.path.normpath(os.path.join(BASE_DIR, rel))
        if not target.startswith(BASE_DIR) or not os.path.isfile(target):
            self.send_response(404)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        size = os.path.getsize(target)
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"

        rng = self.headers.get("Range")
        start, end = 0, size - 1
        partial = False
        if rng:
            m = RANGE_RE.search(rng)
            if m:
                s, e = m.group(1), m.group(2)
                if s:
                    start = int(s)
                    end = int(e) if e else size - 1
                else:                       # bytes=-N  (הסוף של הקובץ)
                    start = max(0, size - int(e))
                    end = size - 1
                if start >= size:
                    self.send_response(416)
                    self._cors()
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                partial = True

        if DELAY_MS and not rel.startswith("__"):
            time.sleep(DELAY_MS / 1000.0)

        length = end - start + 1
        self.send_response(206 if partial else 200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

        if head_only:
            return
        bump(rel, length, partial)
        try:
            with open(target, "rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    chunk = fh.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--delay", type=float, default=0.0,
                    help="השהיה מדומה לכל בקשה במילישניות, לדימוי השהיית רשת")
    args = ap.parse_args()
    global DELAY_MS
    DELAY_MS = args.delay
    if DELAY_MS:
        print(f"השהיה מדומה: {DELAY_MS} מ\"ש לכל בקשה")
    print(f"שרת בדיקה עם תמיכה ב-Range: http://127.0.0.1:{args.port}/")
    print(f"מגיש מתוך: {BASE_DIR}")
    print("לעצירה: Ctrl+C")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nנעצר.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    main()
