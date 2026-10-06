import pathlib
import unittest

from shop import orders
from shop.invoice import invoice
from shop.report import daily


class HiddenRename(unittest.TestCase):
    def test_new_name(self):
        self.assertEqual(orders.order_total([{"qty": 3, "price": 10}]), 30)
        self.assertEqual(orders.order_total([{"qty": 1, "price": 100}], discount=0.25), 75)

    def test_old_name_gone(self):
        self.assertFalse(hasattr(orders, "calc_total"))
        for f in pathlib.Path("shop").glob("*.py"):
            self.assertNotIn("calc_total", f.read_text(encoding="utf-8"), f.name)

    def test_callers(self):
        self.assertEqual(invoice("b", [{"qty": 2, "price": 5}])["total"], 10)
        self.assertEqual(daily([[{"qty": 10, "price": 100}]]), [900])
