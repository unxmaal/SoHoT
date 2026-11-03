import unittest

from foundry import shipping


class Shipping(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(shipping.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(shipping.moving_average([5], 1), [5.0])
        self.assertEqual(shipping.moving_average([1, 2, 3], 3), [2.0])

    def test_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_grade(self):
        self.assertEqual(shipping.grade(95), 'A')
        self.assertEqual(shipping.grade(90), 'A')
