import unittest

from tally.common import moving_average
from tally import payroll


class Payroll(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(moving_average([5], 1), [5.0])
        self.assertEqual(moving_average([1, 2, 3], 3), [2.0])

    def test_weighted_mean(self):
        self.assertEqual(payroll.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(payroll.weighted_mean([10, 20], [1, 3]), 17.5)
