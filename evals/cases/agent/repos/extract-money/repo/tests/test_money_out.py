import unittest

from shop.invoice import line
from shop.receipt import receipt


class Output(unittest.TestCase):
    def test_line(self):
        self.assertEqual(line("tea", 123456), "tea: $1,234.56")

    def test_receipt(self):
        self.assertTrue(receipt([("tea", 250), ("cake", -50)]).endswith("$2.00"))
