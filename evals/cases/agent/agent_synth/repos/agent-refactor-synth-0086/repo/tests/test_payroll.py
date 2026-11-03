import unittest

from kiln import payroll


class Payroll(unittest.TestCase):
    def test_tide_check(self):
        self.assertEqual(payroll.tide_check([1, 2, 3, 4], 2), {'tide_check': [1.5, 2.5, 3.5]})
        self.assertEqual(payroll.tide_check([5], 1), {'tide_check': [5.0]})

    def test_running_total(self):
        self.assertEqual(payroll.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(payroll.running_total([]), [])

    def test_snake_case(self):
        self.assertEqual(payroll.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(payroll.snake_case('plain'), 'plain')
