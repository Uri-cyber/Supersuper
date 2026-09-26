# -*- coding: utf-8 -*-
"""בדיקות לבחירת שם התצוגה ולמילות החיפוש (app/names.py).

    python -m unittest discover -s tests -p "test_*.py"
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
import names  # noqa: E402

# השמות האמיתיים של חלב תנובה בקרטון 1 ליטר (7290004131074), 26.09.2026
MILK = [
    ("חלב בקרטון 3% שומן 1 ל", 324),
    ("תנובה חלב3% קרט מהדר", 233),
    ("חלב 3% קרטון מהדרין", 169),
    ("חלב 3% מהדרין", 146),
    ("חלב הומוגני מהדרין 3", 140),
    ("חלב תנובה 3% שומן 1", 98),
    ("**חלב תנובה טרי מהדרין קרטון 3% 1ל", 91),
    ("חלב תנובה 3% בקרטון 1ל' מהדרין", 66),
]


class PickTest(unittest.TestCase):
    def test_brand_wins(self):
        best, alt = names.pick(MILK, "חלב בקרטון 3% שומן 1 ל' פיקוח")
        self.assertIn("תנובה", best, "שם התצוגה חייב לכלול את המותג שרוב הרשתות כותבות")
        self.assertFalse(best.startswith("*"), "כוכביות בקצה מוסרות")

    def test_alt_has_missing_words_only(self):
        best, alt = names.pick(MILK)
        words = alt.split()
        self.assertEqual(len(words), len(set(words)), "בלי כפילויות")
        for w in names.tokens(best):
            self.assertNotIn(w, words, "מילה שכבר בשם התצוגה לא נכנסת שוב")
        self.assertIn("הומוגני", words, "מילה שרק רשת אחת כותבת נכנסת לחיפוש")

    def test_rare_name_not_chosen(self):
        # שם ארוך במיוחד שמופיע בסניף אחד מתוך 500 לא הופך לשם התצוגה
        v = [("קולה זירו 500 מל", 499), ("קולה זירו 500 מל מבצע ענק לזמן מוגבל בלבד", 1)]
        best, _alt = names.pick(v)
        self.assertEqual(best, "קולה זירו 500 מל")

    def test_glued_loses_tie(self):
        v = [("חלב מועשר3%בקבוק1ל יטבתה", 100), ("יטבתה חלב בבקבוק 3% מועשר 1ל", 100)]
        best, _alt = names.pick(v)
        self.assertEqual(best, "יטבתה חלב בבקבוק 3% מועשר 1ל")

    def test_tokens_split_glue(self):
        self.assertEqual(names.tokens("אולטרה16י"), ["אולטרה", "16"])
        self.assertEqual(names.tokens("תחב.לילה 1.5"), ["תחב", "לילה", "1.5"])

    def test_empty_uses_fallback(self):
        self.assertEqual(names.pick([], "שם ישן"), ("שם ישן", ""))
        self.assertEqual(names.pick([("   ", 3)], "שם ישן"), ("שם ישן", ""))


if __name__ == "__main__":
    unittest.main()
