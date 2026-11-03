import unittest

from depot import orders


class Orders(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(orders.is_leap(2024), True)
        self.assertEqual(orders.is_leap(1900), False)
        self.assertEqual(orders.is_leap(2100), False)

    def test_weighted_mean(self):
        self.assertEqual(orders.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(orders.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_clamp(self):
        self.assertEqual(orders.clamp(5, 0, 10), 5)
        self.assertEqual(orders.clamp(-3, 0, 10), 0)
