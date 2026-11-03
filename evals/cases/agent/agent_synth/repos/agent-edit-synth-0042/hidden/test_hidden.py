import unittest

from quarry import payroll
from quarry import billing
from quarry import ledger


class Hidden(unittest.TestCase):
    def test_payroll_snake_case(self):
        self.assertEqual(payroll.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(payroll.snake_case('plain'), 'plain')
        self.assertEqual(payroll.snake_case('A'), 'a')
        self.assertEqual(payroll.snake_case('ShipToCity'), 'ship_to_city')

    def test_payroll_bucket(self):
        self.assertEqual(payroll.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(payroll.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(payroll.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(payroll.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(payroll.bucket(7, []), 0)

    def test_payroll_luhn_valid(self):
        self.assertEqual(payroll.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(payroll.luhn_valid('79927398713'), True)
        self.assertEqual(payroll.luhn_valid('79927398710'), False)
        self.assertEqual(payroll.luhn_valid(''), False)
        self.assertEqual(payroll.luhn_valid('059'), True)

    def test_billing_rle(self):
        self.assertEqual(billing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(billing.rle(''), [])
        self.assertEqual(billing.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(billing.rle('zz'), [('z', 2)])

    def test_billing_invert(self):
        self.assertEqual(billing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(billing.invert({}), {})
        self.assertEqual(billing.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(billing.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_ledger_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(ledger.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(ledger.merge_ranges([]), [])
        self.assertEqual(ledger.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_ledger_grade(self):
        self.assertEqual(ledger.grade(95), 'A')
        self.assertEqual(ledger.grade(90), 'A')
        self.assertEqual(ledger.grade(85), 'B')
        self.assertEqual(ledger.grade(80), 'B')
        self.assertEqual(ledger.grade(61), 'D')
        self.assertEqual(ledger.grade(59), 'F')
        self.assertEqual(ledger.grade(0), 'F')

    def test_feature(self):
        self.assertEqual(payroll.snake_case('Order Total'), 'order_total')
        self.assertEqual(payroll.snake_case('tea-time'), 'tea_time')
