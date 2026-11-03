import unittest

from granary import orders


class Orders(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(orders.percent_change(50, 75), 50.0)
        self.assertEqual(orders.percent_change(200, 150), -25.0)

    def test_weighted_mean(self):
        self.assertEqual(orders.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(orders.weighted_mean([10, 20], [1, 3]), 17.5)
