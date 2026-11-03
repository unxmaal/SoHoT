import unittest

from foundry import budget


class Budget(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(budget.format_cents(0), '$0.00')
        self.assertEqual(budget.format_cents(123456), '$1,234.56')
        self.assertEqual(budget.format_cents(-105), '-$1.05')

    def test_merge_ranges(self):
        self.assertEqual(budget.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(budget.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(budget.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_bucket(self):
        self.assertEqual(budget.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(budget.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(budget.bucket(12, [0, 5, 10]), 3)
