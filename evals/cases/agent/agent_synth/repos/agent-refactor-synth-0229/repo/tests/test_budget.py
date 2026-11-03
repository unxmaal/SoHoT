import unittest

from beacon.budget import snake_case
from beacon import budget


class Budget(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(snake_case('OrderTotal'), 'order_total')
        self.assertEqual(snake_case('plain'), 'plain')
        self.assertEqual(snake_case('A'), 'a')

    def test_median(self):
        self.assertEqual(budget.median([3, 1, 2]), 2)
        self.assertEqual(budget.median([4, 1, 3, 2]), 2.5)
