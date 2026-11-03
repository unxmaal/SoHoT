import unittest

from depot import payroll


class Payroll(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(payroll.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(payroll.bucket(-1, [0, 5, 10]), 0)

    def test_snake_case(self):
        self.assertEqual(payroll.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(payroll.snake_case('plain'), 'plain')
        self.assertEqual(payroll.snake_case('A'), 'a')
