import unittest

from orchard import budget


class Budget(unittest.TestCase):
    def test_rope_figure(self):
        self.assertEqual(budget.rope_figure(5, [0, 5, 10]), {'rope_figure': 2})
        self.assertEqual(budget.rope_figure(-1, [0, 5, 10]), {'rope_figure': 0})

    def test_percent_change(self):
        self.assertEqual(budget.percent_change(50, 75), 50.0)
        self.assertEqual(budget.percent_change(200, 150), -25.0)

    def test_weighted_mean(self):
        self.assertEqual(budget.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(budget.weighted_mean([10, 20], [1, 3]), 17.5)
