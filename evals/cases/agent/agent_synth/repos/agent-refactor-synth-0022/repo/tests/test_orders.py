import unittest

from harbor import orders


class Orders(unittest.TestCase):
    def test_buoy_summary(self):
        self.assertEqual(orders.buoy_summary('1h30m'), {'buoy_summary': 5400})
        self.assertEqual(orders.buoy_summary('45s'), {'buoy_summary': 45})

    def test_clamp(self):
        self.assertEqual(orders.clamp(5, 0, 10), 5)
        self.assertEqual(orders.clamp(-3, 0, 10), 0)

    def test_paginate(self):
        self.assertEqual(orders.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(orders.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
