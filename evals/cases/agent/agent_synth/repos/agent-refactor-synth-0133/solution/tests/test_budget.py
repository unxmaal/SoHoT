import unittest

from depot.textual import running_total
from depot import budget


class Budget(unittest.TestCase):
    def test_running_total(self):
        self.assertEqual(running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(running_total([]), [])
        self.assertEqual(running_total([5]), [5])

    def test_snake_case(self):
        self.assertEqual(budget.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(budget.snake_case('plain'), 'plain')
