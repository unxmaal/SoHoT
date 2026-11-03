import unittest

from lantern import shipping


class Shipping(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertEqual(shipping.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(shipping.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_invert(self):
        self.assertEqual(shipping.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(shipping.invert({}), {})
