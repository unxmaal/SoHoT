import unittest

from orchard.orders import is_leap
from orchard import orders


class Orders(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(is_leap(2024), True)
        self.assertEqual(is_leap(1900), False)
        self.assertEqual(is_leap(2000), True)

    def test_format_cents(self):
        self.assertEqual(orders.format_cents(0), '$0.00')
        self.assertEqual(orders.format_cents(123456), '$1,234.56')
