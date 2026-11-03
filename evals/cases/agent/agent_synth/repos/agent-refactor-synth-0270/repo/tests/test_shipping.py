import unittest

from beacon import shipping


class Shipping(unittest.TestCase):
    def test_harbor_check(self):
        self.assertEqual(shipping.harbor_check([(1, 3), (3, 5)]), {'harbor_check': [(1, 5)]})
        self.assertEqual(shipping.harbor_check([(5, 6), (1, 2)]), {'harbor_check': [(1, 2), (5, 6)]})

    def test_weighted_mean(self):
        self.assertEqual(shipping.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(shipping.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_rle(self):
        self.assertEqual(shipping.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(shipping.rle(''), [])
