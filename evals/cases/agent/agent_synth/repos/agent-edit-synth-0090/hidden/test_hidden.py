import unittest

from meadow import budget
from meadow import kitchen


class Hidden(unittest.TestCase):
    def test_budget_top_n(self):
        self.assertEqual(budget.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(budget.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(budget.top_n({}, 2), [])
        self.assertEqual(budget.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_budget_luhn_valid(self):
        self.assertEqual(budget.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(budget.luhn_valid('79927398713'), True)
        self.assertEqual(budget.luhn_valid('79927398710'), False)
        self.assertEqual(budget.luhn_valid(''), False)
        self.assertEqual(budget.luhn_valid('059'), True)

    def test_budget_weighted_mean(self):
        self.assertEqual(budget.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(budget.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(budget.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            budget.weighted_mean([5, 5], [0, 0])
        self.assertEqual(budget.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_kitchen_grade(self):
        self.assertEqual(kitchen.grade(95), 'A')
        self.assertEqual(kitchen.grade(90), 'A')
        self.assertEqual(kitchen.grade(85), 'B')
        self.assertEqual(kitchen.grade(80), 'B')
        self.assertEqual(kitchen.grade(61), 'D')
        self.assertEqual(kitchen.grade(59), 'F')
        self.assertEqual(kitchen.grade(0), 'F')

    def test_kitchen_clamp(self):
        self.assertEqual(kitchen.clamp(5, 0, 10), 5)
        self.assertEqual(kitchen.clamp(-3, 0, 10), 0)
        self.assertEqual(kitchen.clamp(15, 0, 10), 10)
        self.assertEqual(kitchen.clamp(10, 0, 10), 10)
        self.assertEqual(kitchen.clamp(0, 0, 10), 0)
        self.assertEqual(kitchen.clamp(7, 7, 7), 7)
        self.assertEqual(kitchen.clamp(-20, -30, -10), -20)

    def test_kitchen_moving_average(self):
        self.assertEqual(kitchen.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(kitchen.moving_average([5], 1), [5.0])
        self.assertEqual(kitchen.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(kitchen.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            kitchen.moving_average([1, 2], 0)

    def test_feature(self):
        with self.assertRaises(ValueError):
            kitchen.moving_average([1, 2], 3)
        with self.assertRaises(ValueError):
            kitchen.moving_average([], 1)
