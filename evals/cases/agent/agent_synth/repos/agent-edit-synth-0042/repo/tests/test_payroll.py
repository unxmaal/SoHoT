import unittest

from quarry import payroll


class Payroll(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(payroll.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(payroll.snake_case('plain'), 'plain')
        self.assertEqual(payroll.snake_case('A'), 'a')

    def test_bucket(self):
        self.assertEqual(payroll.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(payroll.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(payroll.bucket(12, [0, 5, 10]), 3)

    def test_luhn_valid(self):
        self.assertEqual(payroll.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(payroll.luhn_valid('79927398713'), True)
        self.assertEqual(payroll.luhn_valid('79927398710'), False)
