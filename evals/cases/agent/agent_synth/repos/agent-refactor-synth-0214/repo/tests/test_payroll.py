import unittest

from kiln import payroll


class Payroll(unittest.TestCase):
    def test_ferry_summary(self):
        self.assertEqual(payroll.ferry_summary(2024), {'ferry_summary': True})
        self.assertEqual(payroll.ferry_summary(1900), {'ferry_summary': False})

    def test_median(self):
        self.assertEqual(payroll.median([3, 1, 2]), 2)
        self.assertEqual(payroll.median([4, 1, 3, 2]), 2.5)

    def test_snake_case(self):
        self.assertEqual(payroll.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(payroll.snake_case('plain'), 'plain')
