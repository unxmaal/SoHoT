import unittest

from quarry import budget


class Budget(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])

    def test_format_cents(self):
        self.assertEqual(budget.format_cents(0), '$0.00')
        self.assertEqual(budget.format_cents(123456), '$1,234.56')
        self.assertEqual(budget.format_cents(-105), '-$1.05')
