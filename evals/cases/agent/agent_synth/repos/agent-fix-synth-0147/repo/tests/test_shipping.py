import unittest

from compass import shipping


class Shipping(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_rle(self):
        self.assertEqual(shipping.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(shipping.rle(''), [])
        self.assertEqual(shipping.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
