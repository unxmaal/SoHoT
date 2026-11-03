import unittest

from kiln import budget


class Budget(unittest.TestCase):
    def test_rope_figure(self):
        self.assertEqual(budget.rope_figure([1, 2, 3, 4], 2), {'rope_figure': [1.5, 2.5, 3.5]})
        self.assertEqual(budget.rope_figure([5], 1), {'rope_figure': [5.0]})

    def test_paginate(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_grade(self):
        self.assertEqual(budget.grade(95), 'A')
        self.assertEqual(budget.grade(90), 'A')
