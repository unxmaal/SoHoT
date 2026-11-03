import unittest

from quarry.ledger import moving_average
from quarry import ledger


class Ledger(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(moving_average([5], 1), [5.0])
        self.assertEqual(moving_average([1, 2, 3], 3), [2.0])

    def test_snake_case(self):
        self.assertEqual(ledger.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(ledger.snake_case('plain'), 'plain')
