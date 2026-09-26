# -*- coding: utf-8 -*-
"""
שם תצוגה ומילות חיפוש לכל מוצר, מתוך כל השמות שהרשתות נותנות לו.

אותו ברקוד מופיע אצל כל רשת בשם אחר. נמדד: חלב תנובה בקרטון 1 ליטר מופיע
ב-1,670 סניפים תחת 12 שמות שונים, והשם שנבחר קודם (הראשון שנקלט) היה
היחיד שאין בו "תנובה". מי שחיפש "חלב תנובה" לא מצא את המוצר הנפוץ בארץ.

* שם התצוגה: מבין השמות שמופיעים בחלק ממשי מהסניפים, זה שמכסה הכי טוב
  את המילים שרוב הרשתות כותבות. שם שיש בו המותג, הסוג והגודל ("חלב תנובה
  טרי מהדרין קרטון 3% 1ל") עדיף על שם שחסר בו המותג ("חלב בקרטון 3% שומן 1 ל").
* מילות החיפוש: כל מילה שמופיעה בשם של רשת כלשהי ולא בשם התצוגה. רק
  המילים החדשות, ולא השמות המלאים, כדי שאינדקס החיפוש לא יתנפח - החיפוש
  באתר קורא את האינדקס דרך הרשת, וכל מגה נוסף הוא זמן המתנה.
"""
import re

# שם שמופיע בפחות מזה מתוך הסניפים לא נבחר כשם תצוגה (עדיין נכנס לחיפוש)
MIN_SHARE = 0.05
MIN_STORES = 2
MAX_ALT_TOKENS = 24

# מספר (כולל עשרוני), מילה לטינית או מילה עברית. ספרה שדבוקה לאות נחשבת
# מילה נפרדת ("אולטרה16י" = אולטרה, 16), ונקודה אינה חלק ממילה ("תחב.לילה"
# = תחב, לילה). אחרת קיצור דחוס נראה "מפורט" יותר מהשם המלא.
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+|[א-ת]+")
_STRIP = re.compile(r"^[\s*#!\-_.,:;'\"()\[\]{}|/\\]+|[\s*#!\-_.,:;'\"()\[\]{}|/\\]+$")


def clean(name):
    """מסיר כוכביות ופיסוק מהקצוות ורווחים כפולים. לא נוגע באמצע השם."""
    s = re.sub(r"\s+", " ", str(name or "")).strip()
    return _STRIP.sub("", s).strip()


# אות דבוקה לספרה, או נקודה בין שתי אותיות: "מועשר3%בקבוק1ל", "גל.קרמיסימו"
_GLUE = re.compile(r"[a-zא-ת]\d|\d[a-zא-ת]|[a-zא-ת]\.[a-zא-ת]")


def glued(name):
    return len(_GLUE.findall(name.lower()))


def tokens(name):
    return [t for t in _TOKEN.findall(name.lower()) if len(t) >= 2 or t.isdigit()]


def pick(variants, fallback=None):
    """
    variants: [(שם, מספר סניפים)]. מחזיר (שם תצוגה, מילות חיפוש נוספות).
    """
    cleaned = {}
    for name, n in variants:
        c = clean(name)
        if c:
            cleaned[c] = cleaned.get(c, 0) + n
    if not cleaned:
        return (fallback or ""), ""
    total = sum(cleaned.values())
    floor = max(MIN_STORES, total * MIN_SHARE)
    eligible = [(c, n) for c, n in cleaned.items() if n >= floor] or \
               [max(cleaned.items(), key=lambda x: x[1])]
    # כל מילה מקבלת משקל לפי חלק הסניפים שבשם שלהם היא מופיעה. שם שמכיל
    # את המילים שרוב הרשתות מסכימות עליהן (מותג, סוג, גודל) מנצח; מילה
    # שרק רשת אחת כותבת ("מבצע", "ענק") כמעט לא מוסיפה. קנס קטן על טקסט
    # דחוס, ובשוויון השם הנפוץ יותר.
    weight = {}
    for c, n in cleaned.items():
        for t in set(tokens(c)):
            weight[t] = weight.get(t, 0) + n / total

    def score(item):
        c, n = item
        return (round(sum(weight[t] for t in set(tokens(c))) - 0.3 * glued(c), 6), n, -len(c))

    best = max(eligible, key=score)[0]

    have = set(tokens(best))
    extra = []
    for c, _n in sorted(cleaned.items(), key=lambda x: -x[1]):
        for t in tokens(c):
            if t not in have:
                have.add(t)
                extra.append(t)
                if len(extra) >= MAX_ALT_TOKENS:
                    break
        if len(extra) >= MAX_ALT_TOKENS:
            break
    return best, " ".join(extra)
