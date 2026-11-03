import unittest

from quarry.budget import top_n
from quarry import budget


class Budget(unittest.TestCase):
    def test_top_n(self):
        self.assertEqual(top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(top_n({'a': 1}, 5), ['a'])
        self.assertEqual(top_n({}, 2), [])

    def test_moving_average(self):
        self.assertEqual(budget.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(budget.moving_average([5], 1), [5.0])
