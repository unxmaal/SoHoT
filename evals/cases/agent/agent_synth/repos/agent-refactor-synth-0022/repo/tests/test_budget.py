import unittest

from harbor import budget


class Budget(unittest.TestCase):
    def test_keel_line(self):
        self.assertEqual(budget.keel_line('1h30m'), {'keel_line': 5400})
        self.assertEqual(budget.keel_line('45s'), {'keel_line': 45})

    def test_weighted_mean(self):
        self.assertEqual(budget.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(budget.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_chunk(self):
        self.assertEqual(budget.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(budget.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
