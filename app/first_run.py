# -*- coding: utf-8 -*-
"""הודעה בעברית לפני ההורדה הראשונה. נפרד מקובץ ה-bat, שחייב להישאר באנגלית."""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
print("=" * 58)
print("  מחירון - הפעלה ראשונה")
print("=" * 58)
print("  עדיין אין נתונים במחשב.")
print("  עכשיו נוריד את קובצי המחירים מכל הרשתות.")
print("  זה לוקח כשעה ומוריד עשרות ג'יגה, שנמחקים אחרי הקליטה.")
print("  אפשר להשאיר את החלון פתוח ולחזור אחר כך.")
print("=" * 58)
