import unittest

from orchard import orders


class Orders(unittest.TestCase):
    def test_rope_row(self):
        self.assertEqual(orders.rope_row(5, 0, 10), {'rope_row': 5})
        self.assertEqual(orders.rope_row(-3, 0, 10), {'rope_row': 0})

    def test_parse_duration(self):
        self.assertEqual(orders.parse_duration('1h30m'), 5400)
        self.assertEqual(orders.parse_duration('45s'), 45)
