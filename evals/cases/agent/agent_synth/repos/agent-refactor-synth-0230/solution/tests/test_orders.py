import unittest

from orchard.orders import has_feb_29
from orchard import orders


class Orders(unittest.TestCase):
    def test_has_feb_29(self):
        self.assertEqual(has_feb_29(2024), True)
        self.assertEqual(has_feb_29(1900), False)
        self.assertEqual(has_feb_29(2000), True)

    def test_format_cents(self):
        self.assertEqual(orders.format_cents(0), '$0.00')
        self.assertEqual(orders.format_cents(123456), '$1,234.56')
