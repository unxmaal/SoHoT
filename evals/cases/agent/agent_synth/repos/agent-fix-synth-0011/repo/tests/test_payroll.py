import unittest

from orchard import payroll


class Payroll(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(payroll.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(payroll.moving_average([5], 1), [5.0])

    def test_rle(self):
        self.assertEqual(payroll.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(payroll.rle(''), [])
