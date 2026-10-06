import pathlib
import unittest

from shop import money
from shop.invoice import line
from shop.receipt import receipt


class HiddenMoney(unittest.TestCase):
    def test_format(self):
        self.assertEqual(money.format_cents(0), "$0.00")
        self.assertEqual(money.format_cents(123456789), "$1,234,567.89")
        self.assertEqual(money.format_cents(-105), "-$1.05")

    def test_no_duplicates(self):
        for name in ("invoice.py", "receipt.py"):
            text = pathlib.Path("shop", name).read_text(encoding="utf-8")
            self.assertNotIn("def _fmt", text, name)
            self.assertIn("format_cents", text, name)

    def test_outputs_unchanged(self):
        self.assertEqual(line("tea", 123456), "tea: $1,234.56")
        self.assertIn("TOTAL", receipt([("a", 1), ("b", 2)]))
        self.assertTrue(receipt([("a", 100), ("b", 5)]).endswith("$1.05"))
