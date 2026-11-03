import unittest

from harbor import shipping
from harbor import budget


class Hidden(unittest.TestCase):
    def test_shipping_median(self):
        self.assertEqual(shipping.median([3, 1, 2]), 2)
        self.assertEqual(shipping.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(shipping.median([5]), 5)
        self.assertEqual(shipping.median([1, 2]), 1.5)
        self.assertEqual(shipping.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            shipping.median([])

    def test_shipping_moving_average(self):
        self.assertEqual(shipping.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(shipping.moving_average([5], 1), [5.0])
        self.assertEqual(shipping.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(shipping.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            shipping.moving_average([1, 2], 0)

    def test_shipping_grade(self):
        self.assertEqual(shipping.grade(95), 'A')
        self.assertEqual(shipping.grade(90), 'A')
        self.assertEqual(shipping.grade(85), 'B')
        self.assertEqual(shipping.grade(80), 'B')
        self.assertEqual(shipping.grade(61), 'D')
        self.assertEqual(shipping.grade(59), 'F')
        self.assertEqual(shipping.grade(0), 'F')

    def test_budget_paginate(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(budget.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            budget.paginate([1, 2], 0, 2)

    def test_budget_weighted_mean(self):
        self.assertEqual(budget.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(budget.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(budget.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            budget.weighted_mean([5, 5], [0, 0])
        self.assertEqual(budget.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_budget_clamp(self):
        self.assertEqual(budget.clamp(5, 0, 10), 5)
        self.assertEqual(budget.clamp(-3, 0, 10), 0)
        self.assertEqual(budget.clamp(15, 0, 10), 10)
        self.assertEqual(budget.clamp(10, 0, 10), 10)
        self.assertEqual(budget.clamp(0, 0, 10), 0)
        self.assertEqual(budget.clamp(7, 7, 7), 7)
        self.assertEqual(budget.clamp(-20, -30, -10), -20)

    def test_feature(self):
        self.assertEqual(shipping.median([], default=0), 0)
        self.assertEqual(shipping.median([], default=-1), -1)
        self.assertEqual(shipping.median([1, 3], default=0), 2.0)
