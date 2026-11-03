import unittest

from tally import ledger


class Ledger(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(ledger.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(ledger.snake_case('plain'), 'plain')
        self.assertEqual(ledger.snake_case('A'), 'a')

    def test_paginate(self):
        self.assertEqual(ledger.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(ledger.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
