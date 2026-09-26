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

    def test_city_from_name(self):
        rows = {r[0]: r for r in parse(CITY_MARKET_XML)}
        self.assertEqual(rows[40][2], "תל אביב - יפו")
        self.assertEqual(rows[40][3], "קלישר 3", "הכתובת: הקטע שאחרי הפסיק, בלי העיר")
        self.assertIn("משם הסניף", rows[40][4], "מקור העיר מתועד בהערה")
        self.assertEqual(rows[12][2], "כפר סבא", "קיצור מקובל בסוף השם")

    def test_no_city_stays_unknown(self):
        rows = {r[0]: r for r in parse(CITY_MARKET_XML)}
        self.assertEqual(rows[1][2], ip.UNKNOWN, "שם בלי עיר בסופו: לא מנחשים")
        self.assertEqual(rows[1][3], ip.UNKNOWN)

    def test_regular_file_unchanged(self):
        rows = parse(REGULAR_XML)
        self.assertEqual(rows, [(7, "רמת אביב", "תל אביב - יפו", "איינשטיין 40", "")])

    def test_city_only_at_end(self):
        city, _rest = ip.city_from_store_name("סיטי מרקט וייצמן כפר סבא, וייצמן 55")
        self.assertIsNone(city, "עיר באמצע השם אינה נלקחת")


if __name__ == "__main__":
    unittest.main()
