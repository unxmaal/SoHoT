import unittest

from mill import ledger
from mill import shipping


class Hidden(unittest.TestCase):
    def test_ledger_moving_average(self):
        self.assertEqual(ledger.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(ledger.moving_average([5], 1), [5.0])
        self.assertEqual(ledger.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(ledger.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            ledger.moving_average([1, 2], 0)

    def test_ledger_bucket(self):
        self.assertEqual(ledger.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(ledger.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(ledger.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(ledger.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(ledger.bucket(7, []), 0)

    def test_shipping_top_n(self):
        self.assertEqual(shipping.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(shipping.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(shipping.top_n({}, 2), [])
        self.assertEqual(shipping.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_shipping_parse_duration(self):
        self.assertEqual(shipping.parse_duration('1h30m'), 5400)
        self.assertEqual(shipping.parse_duration('45s'), 45)
        self.assertEqual(shipping.parse_duration('2h'), 7200)
        self.assertEqual(shipping.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            shipping.parse_duration('')
        with self.assertRaises(ValueError):
            shipping.parse_duration('5x')
        self.assertEqual(shipping.parse_duration('10m5s'), 605)

    def test_shipping_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(shipping.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            shipping.paginate([1, 2], 0, 2)

    def test_feature(self):
        self.assertEqual(shipping.top_n({'tea': 3, 'milk': 1, 'jam': 2}, 5, min_count=2), ['tea', 'jam'])
