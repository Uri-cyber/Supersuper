# -*- coding: utf-8 -*-
"""
מודיע למשתמש כשמשהו דורש תשומת לב, ושותק כשהכול תקין.

ההודעה היא קובץ טקסט על שולחן העבודה, ולא חלון קופץ. שתי סיבות:

1. נמדד שהמשימה המתוזמנת נתקעת על `import ctypes` במחשב הזה. תהליך שהיה
   אמור להציג חלון פשוט נשאר תלוי, ואף הודעה לא הגיעה. קובץ נכתב בלי שום
   ספרייה חיצונית ולכן אינו יכול להיתקע.
2. חלון קופץ נסגר ונשכח. קובץ על שולחן העבודה נשאר עד שמטפלים בו, וזה
   בדיוק ההתנהגות הרצויה כשעדכון נכשל בזמן שאיש לא ליד המחשב.

הקובץ נמחק לבד ברגע שריצה מצליחה, כדי שלא יישאר להפחיד אחרי שהבעיה נפתרה.
"""
import io
import json
import os
import shutil
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(BASE_DIR)
STATE_PATH = os.path.join(BASE_DIR, "last_run.json")

ALERT_NAME = "מחירון - צריך טיפול.txt"
STALE_HOURS = 36
LOW_FREE_GB = 25
GB = 1024 ** 3


def desktop_dirs():
    """
    שולחן העבודה יכול לשבת גם תחת OneDrive. כותבים לכל מה שקיים, כי עדיף
    שני עותקים מאשר הודעה שנכתבה למקום שהמשתמש לא רואה.
    """
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    out = []
    for p in (os.path.join(home, "Desktop"),
              os.path.join(home, "OneDrive", "Desktop")):
        if os.path.isdir(p):
            out.append(p)
    return out or [home]


def write_alert(text):
    for d in desktop_dirs():
        try:
            io.open(os.path.join(d, ALERT_NAME), "w", encoding="utf-8").write(text)
        except OSError:
            pass


def clear_alert():
    for d in desktop_dirs():
        try:
            os.remove(os.path.join(d, ALERT_NAME))
        except OSError:
            pass


def problems():
    """רשימת הדברים שדורשים טיפול. רשימה ריקה פירושה שהכול בסדר."""
    out = []
    try:
        data = json.loads(io.open(STATE_PATH, encoding="utf-8").read())
    except Exception:  # noqa: BLE001
        data = None

    if data is not None:
        if not data.get("ok"):
            out.append("העדכון האחרון נכשל.\n" + (data.get("message") or ""))
        else:
            try:
                ts = time.mktime(time.strptime(data.get("finished", ""),
                                               "%Y-%m-%d %H:%M:%S"))
                if (time.time() - ts) / 3600.0 > STALE_HOURS:
                    out.append(f"המחירים לא התעדכנו מאז {data['finished']}.\n"
                               "כנראה שהמחשב היה כבוי. אפשר להריץ עדכון ידני.")
            except Exception:  # noqa: BLE001
                pass

    try:
        free = shutil.disk_usage(REPO_DIR).free / GB
        if free < LOW_FREE_GB:
            out.append(f"נשארו {free:.0f} ג'יגה פנויים בכונן.\n"
                       "אפשר לפנות מקום, או להעביר היסטוריה ישנה לקובץ נפרד.")
    except OSError:
        pass
    return out


def main():
    probs = problems()
    if not probs:
        clear_alert()
        return 0
    text = ("מחירון - העדכון האוטומטי דורש טיפול\n" +
            time.strftime("%d/%m/%Y %H:%M") + "\n\n" +
            "\n\n".join(probs) +
            "\n\nלבדיקת מצב מלאה: להריץ status.bat בתיקיית הפרויקט.\n"
            "הקובץ הזה נמחק לבד ברגע שעדכון יצליח.\n")
    write_alert(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
