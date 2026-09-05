# -*- coding: utf-8 -*-
"""
ריצה יומית אחת: הורדה, אינדקס, בניית מסד ענן, העלאה, פרסום, ניקוי.

הסדר אינו שרירותי. כל שלב תלוי בקודמו, ושני שלבים בסוף מסוכנים במיוחד:

* `site/config.js` מתעדכן רק אחרי שההעלאה אומתה מול הדלי. אם משנים אותו
  לפני כן ומשהו נכשל, האתר החי מצביע על קובץ שלא קיים - כלומר אתר שבור,
  במקום אתר שמציג נתונים של אתמול.

* הניקוי רץ רק אחרי דחיפה מוצלחת לגיט. כל עוד הדחיפה לא עברה, האתר החי
  עדיין מצביע על הגרסה הקודמת, ומחיקתה הייתה שוברת אותו.

הודעות למשתמש נכתבות כאן ולא בקובץ bat, כי cmd מפרש קובצי bat בקידוד
ANSI ועברית בתוכם הופכת לג'יבריש שמורץ כפקודות.
"""
import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(BASE_DIR)
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOCK_PATH = os.path.join(BASE_DIR, ".daily.lock")
STATE_PATH = os.path.join(BASE_DIR, "last_run.json")
CONFIG_JS = os.path.join(REPO_DIR, "site", "config.js")

MIN_FREE_GB = 15          # build_cloud_db כותב כ-2 ג'יגה ואז VACUUM שדורש עותק נוסף
LOG_KEEP_DAYS = 30

_log_fh = None


def log(msg=""):
    print(msg, flush=True)
    if _log_fh:
        _log_fh.write(msg + "\n")
        _log_fh.flush()


# ------------------------------------------------------------------ נעילה
def acquire_lock():
    """
    מנעול שמונע שתי ריצות במקביל.

    לא קובץ-דגל: ריצה שקרסה הייתה משאירה אותו מאחור וחוסמת את כל הריצות
    הבאות. מנעול בייט משוחרר על ידי מערכת ההפעלה כשהתהליך מת, מכל סיבה.
    """
    try:
        import msvcrt
    except ImportError:
        return open(LOCK_PATH, "w")      # לא ווינדוס: אין נעילה, אבל אין גם משימה מתוזמנת
    fh = open(LOCK_PATH, "a+")
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return fh
    except OSError:
        fh.close()
        return None


# ------------------------------------------------------------------ עזרים
def free_gb(path):
    return shutil.disk_usage(path).free / (1024 ** 3)


def live_key():
    """המפתח שהאתר מצביע עליו כרגע, לפי site/config.js."""
    try:
        text = io.open(CONFIG_JS, encoding="utf-8").read()
    except OSError:
        return None
    m = re.search(r'dbUrl:\s*"([^"]+)"', text)
    if not m:
        return None
    return m.group(1).rstrip("/").split("/")[-1]


def run_step(title, argv, cwd=REPO_DIR):
    """מריץ שלב ומחזיר את קוד היציאה. הפלט נכנס גם למסך וגם ליומן."""
    log("")
    log("=" * 60)
    log(title)
    log("=" * 60)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    t0 = time.time()
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", bufsize=1)
    for line in proc.stdout:
        log(line.rstrip("\n"))
    proc.wait()
    log(f"[{title}] הסתיים אחרי {int(time.time() - t0)} שניות, קוד {proc.returncode}")
    return proc.returncode


def announce(data):
    """
    מעדכן את ההודעה על שולחן העבודה: כותב אותה כשיש בעיה, ומוחק כשאין.

    נקרא מכאן ולא ממשימה מתוזמנת נפרדת, כי נמדד שתהליך פייתון שנפתח על ידי
    לוח המשימות נתקע על טעינת ספריות מסוימות. השלב הזה רץ בתוך ריצה שכבר
    עובדת, ולכן הוא אמין.
    """
    try:
        sys.path.insert(0, BASE_DIR)
        import notify
        notify.main()
    except Exception as exc:  # noqa: BLE001
        log(f"לא הצלחתי לעדכן את ההודעה על שולחן העבודה: {exc}")


def write_state(ok, stage, message, key=None, started=None):
    data = {
        "ok": bool(ok),
        "stage": stage,
        "message": message,
        "key": key,
        "started": started,
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
        "free_gb": round(free_gb(REPO_DIR), 1),
    }
    io.open(STATE_PATH, "w", encoding="utf-8").write(
        json.dumps(data, ensure_ascii=False, indent=2))
    announce(data)
    return data


def record_db_size():
    """
    רושם את גודל prices.db בכל ריצה.

    כך קצב הגידול נמדד בפועל בין ריצות, במקום להיגזר ממכפלת רשומות בבתים -
    הערכה שיוצאת שגויה כי שורות היסטוריה ושורות מחיר אינן באותו גודל.
    """
    path = os.path.join(BASE_DIR, "size_history.json")
    db = os.path.join(REPO_DIR, "prices.db")
    try:
        samples = json.loads(io.open(path, encoding="utf-8").read())
    except Exception:  # noqa: BLE001
        samples = []
    try:
        samples.append({"t": int(time.time()), "bytes": os.path.getsize(db)})
    except OSError:
        return
    samples = samples[-120:]
    io.open(path, "w", encoding="utf-8").write(json.dumps(samples))


def rotate_logs():
    """יומנים ישנים נמחקים, כדי שהם עצמם לא יהפכו לבעיית אחסון."""
    cutoff = time.time() - LOG_KEEP_DAYS * 86400
    try:
        for name in os.listdir(LOG_DIR):
            p = os.path.join(LOG_DIR, name)
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
    except OSError:
        pass


def git(args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    return subprocess.run(["git", "-C", REPO_DIR] + args, env=env,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


# ------------------------------------------------------------------ הראשי
def main():
    global _log_fh
    ap = argparse.ArgumentParser(description="עדכון יומי מלא של מחירון")
    ap.add_argument("--no-scrape", action="store_true",
                    help="לדלג על ההורדה מהרשתות (לבדיקות)")
    ap.add_argument("--no-publish", action="store_true",
                    help="לא לדחוף לגיט. האתר החי לא יתעדכן")
    ap.add_argument("--max-gb", type=float, default=9.0,
                    help="גבול תפוסה בדלי בג'יגה")
    args = ap.parse_args()

    lock = acquire_lock()
    if lock is None:
        print("כבר רצה כרגע ריצה יומית. יוצא.")
        return 0

    os.makedirs(LOG_DIR, exist_ok=True)
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    _log_fh = io.open(os.path.join(LOG_DIR, time.strftime("%Y-%m-%d") + ".log"),
                      "a", encoding="utf-8")
    log("")
    log("#" * 60)
    log(f"# עדכון יומי - {started}")
    log("#" * 60)

    # ---------- בדיקות מקדימות
    free = free_gb(REPO_DIR)
    log(f"מקום פנוי בכונן: {free:.1f} GB")
    if free < MIN_FREE_GB:
        msg = (f"נשארו רק {free:.1f} GB פנויים. העדכון לא רץ כדי לא למלא את הכונן. "
               "אפשר לפנות מקום, או להעביר היסטוריה ישנה לקובץ נפרד.")
        log(msg)
        write_state(False, "preflight", msg, started=started)
        return 1
    if not os.path.exists(os.path.join(REPO_DIR, "prices.db")):
        msg = "לא נמצא prices.db. צריך להריץ קודם: il_prices.py update"
        log(msg)
        write_state(False, "preflight", msg, started=started)
        return 1

    protect = live_key()
    log(f"האתר מצביע כרגע על: {protect or 'לא ידוע'}")

    py = sys.executable

    # ---------- הורדה
    if not args.no_scrape:
        if run_step("1/5 מוריד מחירים מהרשתות", [py, "il_prices.py", "update"]):
            msg = "ההורדה מהרשתות נכשלה. לא בוצע שום שינוי באתר."
            write_state(False, "update", msg, started=started)
            return 1
    else:
        log("דילוג על ההורדה (--no-scrape)")

    # ---------- אינדקס
    if run_step("2/5 בונה את האינדקס", [py, os.path.join("app", "build_index.py"), "--force"]):
        msg = "בניית האינדקס נכשלה. הנתונים ירדו אבל האתר לא עודכן."
        write_state(False, "index", msg, started=started)
        return 1

    # ---------- מסד הענן
    if run_step("3/5 בונה את מסד הענן",
                [py, os.path.join("cloud", "build_cloud_db.py")]):
        msg = "בניית מסד הענן נכשלה. האתר לא עודכן."
        write_state(False, "build", msg, started=started)
        return 1

    # ---------- העלאה. הניקוי לא רץ כאן אלא רק אחרי דחיפה מוצלחת.
    up = [py, os.path.join("cloud", "upload_r2.py"),
          "--no-prune", "--max-gb", str(args.max_gb)]
    if protect:
        up += ["--protect-key", protect]
    if run_step("4/5 מעלה לענן", up):
        msg = "ההעלאה לענן נכשלה. האתר ממשיך להציג את הנתונים הקודמים."
        write_state(False, "upload", msg, started=started)
        return 1

    new_key = live_key()
    if not new_key or new_key == protect:
        # ההעלאה הצליחה אבל config.js לא השתנה. אין מה לפרסם, ואסור לנחש.
        msg = "ההעלאה הסתיימה אבל site/config.js לא השתנה. האתר לא עודכן."
        log(msg)
        write_state(False, "upload", msg, key=new_key, started=started)
        return 1
    log(f"הקובץ החדש: {new_key}")

    # ---------- פרסום
    if args.no_publish:
        log("דילוג על הפרסום (--no-publish). האתר החי לא יתעדכן.")
        write_state(True, "done", f"עלה {new_key} בלי פרסום לאתר.",
                    key=new_key, started=started)
        return 0

    ok, msg = publish(new_key)
    if not ok:
        write_state(False, "publish", msg, key=new_key, started=started)
        return 1

    # ---------- ניקוי. רק עכשיו בטוח: האתר כבר מצביע על החדש.
    prune(new_key)

    record_db_size()
    rotate_logs()
    data = write_state(True, "done", f"עודכן ל-{new_key}.", key=new_key, started=started)
    log("")
    log(f"הסתיים בהצלחה. מקום פנוי: {data['free_gb']} GB")
    return 0


def publish(new_key):
    """דוחף רק את site/config.js. לעולם לא -A: קובץ אחד, בכוונה."""
    log("")
    log("=" * 60)
    log("5/5 מפרסם לאתר")
    log("=" * 60)
    r = git(["add", "site/config.js"])
    if r.returncode:
        return False, "git add נכשל: " + (r.stderr or "").strip()[:200]
    if git(["diff", "--cached", "--quiet", "site/config.js"]).returncode == 0:
        log("אין שינוי ב-config.js. אין מה לפרסם.")
        return True, "אין שינוי לפרסום."
    r = git(["commit", "-m", "Publish the " + time.strftime("%d.%m") + " data"])
    if r.returncode:
        return False, "git commit נכשל: " + (r.stdout or r.stderr or "").strip()[:200]
    log(r.stdout.strip())
    r = git(["push", "origin", "HEAD:main"])
    if r.returncode:
        # הנתונים בענן. רק הפרסום נכשל, והאתר ממשיך על הגרסה הקודמת.
        return False, ("ההעלאה לענן הצליחה, אבל הפרסום לאתר נכשל. האתר עדיין מציג "
                       "את הנתונים הקודמים. צריך להתחבר מחדש לגיטהאב. "
                       + (r.stderr or "").strip()[:200])
    log("נדחף לגיטהאב. האתר יתעדכן תוך דקה.")
    return True, "פורסם."


def prune(new_key):
    log("")
    log("מנקה גרסאות ישנות בדלי:")
    sys.path.insert(0, BASE_DIR)
    try:
        import upload_r2
        cfg = upload_r2.load_config()
        if not cfg:
            log("  אין הגדרות ענן. דילוג.")
            return
        upload_r2.prune_old(cfg, new_key, keep=1, protect_keys=[new_key])
        _objs, after = upload_r2.bucket_usage(cfg)
        log(f"  תפוסה בדלי: {after / upload_r2.GB:.2f} GB")
    except Exception as exc:  # noqa: BLE001
        # כישלון ניקוי אינו שובר כלום: הקובץ עלה והאתר מעודכן.
        log(f"  הניקוי נכשל: {exc}")


if __name__ == "__main__":
    sys.exit(main())
