import unittest

from beacon import budget


class Budget(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(budget.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(budget.snake_case('plain'), 'plain')
        self.assertEqual(budget.snake_case('A'), 'a')

    def test_moving_average(self):
        self.assertEqual(budget.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(budget.moving_average([5], 1), [5.0])
        self.assertEqual(budget.moving_average([1, 2, 3], 3), [2.0])

    def test_merge_ranges(self):
        self.assertEqual(budget.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(budget.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(budget.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
