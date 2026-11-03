import unittest

from beacon import budget


class Budget(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(budget.word_count('a b'), 2)
        self.assertEqual(budget.word_count('  tea  and   milk '), 3)
        self.assertEqual(budget.word_count(''), 0)

    def test_paginate(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])

    def test_merge_ranges(self):
        self.assertEqual(budget.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(budget.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(budget.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
