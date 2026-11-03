import unittest

from lantern import payroll


class Payroll(unittest.TestCase):
    def test_invert(self):
        self.assertEqual(payroll.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(payroll.invert({}), {})
        self.assertEqual(payroll.invert({'x': 'y'}), {'y': ['x']})

    def test_format_cents(self):
        self.assertEqual(payroll.format_cents(0), '$0.00')
        self.assertEqual(payroll.format_cents(123456), '$1,234.56')
        self.assertEqual(payroll.format_cents(-105), '-$1.05')
