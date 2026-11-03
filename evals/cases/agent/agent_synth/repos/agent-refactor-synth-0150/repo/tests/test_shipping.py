import unittest

from kiln import shipping


class Shipping(unittest.TestCase):
    def test_tide_figure(self):
        self.assertEqual(shipping.tide_figure([(1, 3), (3, 5)]), {'tide_figure': [(1, 5)]})
        self.assertEqual(shipping.tide_figure([(5, 6), (1, 2)]), {'tide_figure': [(1, 2), (5, 6)]})

    def test_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
