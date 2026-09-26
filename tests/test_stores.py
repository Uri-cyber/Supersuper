# -*- coding: utf-8 -*-
"""בדיקות לקריאת קובצי סניפים (il_prices.py): תג הרשומה של סיטי מרקט,
ועיר שכתובה בסוף שם הסניף כשבשדה העיר כתוב unknown."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import il_prices as ip  # noqa: E402

CITY_MARKET_XML = """<?xml version="1.0" encoding="utf-8"?>
<root><ChainName>סיטי מרקט</ChainName>
<SubChains><SubChainsXMLObject><SubChain><SubChainId>1</SubChainId><SubChainName>x</SubChainName>
<Stores><Store><SubChainStoresXMLObject>
  <SubChainStoreXMLObject><StoreId>040</StoreId><StoreName>מתוק בשוק הכרמל בע"מ, קלישר 3 תל אביב</StoreName>
    <Address>unknown</Address><City>unknown</City></SubChainStoreXMLObject>
  <SubChainStoreXMLObject><StoreId>012</StoreId><StoreName>סיטי מרקט כ"ס, רח' הנשר כ"ס</StoreName>
    <Address>unknown</Address><City>unknown</City></SubChainStoreXMLObject>
  <SubChainStoreXMLObject><StoreId>001</StoreId><StoreName>סיטי מרקט - חנויות כללי</StoreName>
    <Address>unknown</Address><City>unknown</City></SubChainStoreXMLObject>
</SubChainStoresXMLObject></Store></Stores></SubChain></SubChainsXMLObject></SubChains></root>
"""

REGULAR_XML = """<?xml version="1.0" encoding="utf-8"?>
<Root><Stores>
  <Store><StoreId>7</StoreId><StoreName>רמת אביב</StoreName><City>תל אביב - יפו</City><Address>איינשטיין 40</Address></Store>
</Stores></Root>
"""


def parse(xml):
    fd, path = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(xml)
    try:
        return ip.parse_store_file(path)
    finally:
        os.remove(path)


class StoreFileTest(unittest.TestCase):
    def test_city_market_records_are_read(self):
        rows = {r[0]: r for r in parse(CITY_MARKET_XML)}
        self.assertEqual(sorted(rows), [1, 12, 40], "כל סניף ברשומה פנימית נקרא, לא הקובץ כולו כרשומה אחת")

    def test_parse_leaves_city_unknown(self):
        rows = {r[0]: r for r in parse(CITY_MARKET_XML)}
        self.assertEqual(rows[40][2], ip.UNKNOWN, "הקורא עצמו לא מנחש; המילוי משם הסניף הוא מעבר נפרד")

    def test_regular_file_unchanged(self):
        rows = parse(REGULAR_XML)
        self.assertEqual(rows, [(7, "רמת אביב", "תל אביב - יפו", "איינשטיין 40", "")])


ALLOWED = {"תל אביב - יפו", "כפר סבא", "נהריה", "מודיעין-מכבים-רעות", "אשקלון", "חצור-אשדוד", "חצור הגלילית"}
TOKENS = ip.city_tokens(ALLOWED)


class CityFromNameTest(unittest.TestCase):
    def test_end_with_address(self):
        city, rest = ip.city_from_store_name('מתוק בשוק הכרמל בע"מ, קלישר 3 תל אביב', TOKENS)
        self.assertEqual(city, "תל אביב - יפו")
        self.assertEqual(ip.address_from_rest(rest), "קלישר 3")

    def test_abbreviation_at_start_beats_word_at_end(self):
        self.assertEqual(ip.city_from_store_name('ת"א סלמה', TOKENS)[0], "תל אביב - יפו")
        self.assertEqual(ip.city_from_store_name('ת"א - כיכר רבין', TOKENS)[0], "תל אביב - יפו")

    def test_exact_and_hyphen_part(self):
        self.assertEqual(ip.city_from_store_name("נהריה", TOKENS)[0], "נהריה")
        self.assertEqual(ip.city_from_store_name("מודיעין ישפרו", TOKENS)[0], "מודיעין-מכבים-רעות")
        self.assertEqual(ip.city_from_store_name("קולינריק מודיעין", TOKENS)[0], "מודיעין-מכבים-רעות")

    def test_ambiguous_token_dropped(self):
        self.assertNotIn("חצור", TOKENS, "חצור יכול להיות שני יישובים ולכן אינו מזהה")
        self.assertIsNone(ip.city_from_store_name("חצור ת.", TOKENS)[0])

    def test_city_in_the_middle_or_not_allowed(self):
        self.assertIsNone(ip.city_from_store_name("סיטי מרקט וייצמן כפר סבא, וייצמן 55", TOKENS)[0])
        self.assertIsNone(ip.city_from_store_name("אונליין - רמות", TOKENS)[0], "יישוב שאינו ברשימה המותרת")
        self.assertIsNone(ip.city_from_store_name("סיטי מרקט - חנויות כללי", TOKENS)[0])
        self.assertEqual(ip.city_from_store_name("מבקיעים אשקלון", TOKENS)[0], "אשקלון")


if __name__ == "__main__":
    unittest.main()
