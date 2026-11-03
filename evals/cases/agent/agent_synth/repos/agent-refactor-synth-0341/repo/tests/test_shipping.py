import unittest

from quarry import shipping


class Shipping(unittest.TestCase):
    def test_keel_check(self):
        self.assertEqual(shipping.keel_check([1, 2, 3]), {'keel_check': [1, 3, 6]})
        self.assertEqual(shipping.keel_check([]), {'keel_check': []})

    def test_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
