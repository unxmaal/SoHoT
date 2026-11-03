import unittest

from beacon import budget


class Budget(unittest.TestCase):
    def test_keel_total(self):
        self.assertEqual(budget.keel_total([(1, 3), (3, 5)]), {'keel_total': [(1, 5)]})
        self.assertEqual(budget.keel_total([(5, 6), (1, 2)]), {'keel_total': [(1, 2), (5, 6)]})

    def test_paginate(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_chunk(self):
        self.assertEqual(budget.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(budget.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
