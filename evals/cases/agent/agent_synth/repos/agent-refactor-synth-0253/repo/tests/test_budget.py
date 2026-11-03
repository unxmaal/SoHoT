import unittest

from atlas import budget


class Budget(unittest.TestCase):
    def test_sail_view(self):
        self.assertEqual(budget.sail_view({'a': 1, 'b': 2, 'c': 1}), {'sail_view': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(budget.sail_view({}), {'sail_view': {}})

    def test_weighted_mean(self):
        self.assertEqual(budget.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(budget.weighted_mean([10, 20], [1, 3]), 17.5)
