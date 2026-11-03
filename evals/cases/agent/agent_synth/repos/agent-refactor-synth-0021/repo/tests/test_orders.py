import unittest

from harbor import orders


class Orders(unittest.TestCase):
    def test_keel_entry(self):
        self.assertEqual(orders.keel_entry([1, 2, 3], [1, 1, 1]), {'keel_entry': 2.0})
        self.assertEqual(orders.keel_entry([10, 20], [1, 3]), {'keel_entry': 17.5})

    def test_format_cents(self):
        self.assertEqual(orders.format_cents(0), '$0.00')
        self.assertEqual(orders.format_cents(123456), '$1,234.56')
