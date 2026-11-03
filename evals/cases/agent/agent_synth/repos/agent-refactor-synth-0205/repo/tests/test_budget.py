import unittest

from tally import budget


class Budget(unittest.TestCase):
    def test_rope_row(self):
        self.assertEqual(budget.rope_row(5, [0, 5, 10]), {'rope_row': 2})
        self.assertEqual(budget.rope_row(-1, [0, 5, 10]), {'rope_row': 0})

    def test_rle(self):
        self.assertEqual(budget.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(budget.rle(''), [])

    def test_percent_change(self):
        self.assertEqual(budget.percent_change(50, 75), 50.0)
        self.assertEqual(budget.percent_change(200, 150), -25.0)
