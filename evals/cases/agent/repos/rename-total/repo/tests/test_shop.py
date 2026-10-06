import unittest

from shop.invoice import invoice
from shop.report import daily


class Shop(unittest.TestCase):
    def test_invoice(self):
        items = [{"qty": 2, "price": 150}, {"qty": 1, "price": 99}]
        self.assertEqual(invoice("ada", items)["total"], 399)

    def test_daily(self):
        self.assertEqual(daily([[{"qty": 10, "price": 100}]]), [900])
