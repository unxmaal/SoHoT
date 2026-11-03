import unittest

from atlas import ledger


class Ledger(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(ledger.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(ledger.snake_case('plain'), 'plain')

    def test_paginate(self):
        self.assertEqual(ledger.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(ledger.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_invert(self):
        self.assertEqual(ledger.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(ledger.invert({}), {})
