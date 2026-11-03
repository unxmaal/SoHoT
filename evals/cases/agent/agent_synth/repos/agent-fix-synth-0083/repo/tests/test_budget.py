import unittest

from depot import budget


class Budget(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_top_n(self):
        self.assertEqual(budget.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(budget.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(budget.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])
