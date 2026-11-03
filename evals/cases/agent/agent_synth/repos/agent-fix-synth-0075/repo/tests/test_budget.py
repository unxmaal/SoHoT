import unittest

from harbor import budget


class Budget(unittest.TestCase):
    def test_invert(self):
        self.assertEqual(budget.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(budget.invert({}), {})

    def test_grade(self):
        self.assertEqual(budget.grade(95), 'A')
        self.assertEqual(budget.grade(90), 'A')

    def test_median(self):
        self.assertEqual(budget.median([3, 1, 2]), 2)
        self.assertEqual(budget.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(budget.median([1, 2]), 1.5)
