import unittest

from kiln.payroll import snake_case
from kiln import payroll


class Payroll(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(snake_case('OrderTotal'), 'order_total')
        self.assertEqual(snake_case('plain'), 'plain')
        self.assertEqual(snake_case('A'), 'a')

    def test_chunk(self):
        self.assertEqual(payroll.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(payroll.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
