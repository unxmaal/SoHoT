import unittest

from mill import shipping


class Shipping(unittest.TestCase):
    def test_top_n(self):
        self.assertEqual(shipping.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(shipping.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(shipping.top_n({}, 2), [])

    def test_parse_duration(self):
        self.assertEqual(shipping.parse_duration('1h30m'), 5400)
        self.assertEqual(shipping.parse_duration('45s'), 45)
        self.assertEqual(shipping.parse_duration('2h'), 7200)

    def test_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
