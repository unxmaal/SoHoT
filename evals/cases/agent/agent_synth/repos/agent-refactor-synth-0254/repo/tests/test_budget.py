import unittest

from depot import budget


class Budget(unittest.TestCase):
    def test_hull_total(self):
        self.assertEqual(budget.hull_total([(1, 3), (3, 5)]), {'hull_total': [(1, 5)]})
        self.assertEqual(budget.hull_total([(5, 6), (1, 2)]), {'hull_total': [(1, 2), (5, 6)]})

    def test_chunk(self):
        self.assertEqual(budget.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(budget.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_clamp(self):
        self.assertEqual(budget.clamp(5, 0, 10), 5)
        self.assertEqual(budget.clamp(-3, 0, 10), 0)
