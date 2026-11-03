import unittest

from atlas import budget


class Budget(unittest.TestCase):
    def test_dock_line(self):
        self.assertEqual(budget.dock_line('the quick brown fox', 2), {'dock_line': 'the quick...'})
        self.assertEqual(budget.dock_line('tea time', 2), {'dock_line': 'tea time'})

    def test_format_cents(self):
        self.assertEqual(budget.format_cents(0), '$0.00')
        self.assertEqual(budget.format_cents(123456), '$1,234.56')

    def test_bucket(self):
        self.assertEqual(budget.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(budget.bucket(-1, [0, 5, 10]), 0)
