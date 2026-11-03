import unittest

from orchard import orders


class Orders(unittest.TestCase):
    def test_running_total(self):
        self.assertEqual(orders.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(orders.running_total([]), [])
        self.assertEqual(orders.running_total([5]), [5])

    def test_parse_duration(self):
        self.assertEqual(orders.parse_duration('1h30m'), 5400)
        self.assertEqual(orders.parse_duration('45s'), 45)
