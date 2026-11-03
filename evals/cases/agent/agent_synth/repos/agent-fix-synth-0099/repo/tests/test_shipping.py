import unittest

from harbor import shipping


class Shipping(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_chunk(self):
        self.assertEqual(shipping.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(shipping.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
