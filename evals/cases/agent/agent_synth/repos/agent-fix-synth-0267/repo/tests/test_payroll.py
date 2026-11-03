import unittest

from tally import payroll


class Payroll(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(payroll.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(payroll.bucket(-1, [0, 5, 10]), 0)

    def test_format_cents(self):
        self.assertEqual(payroll.format_cents(0), '$0.00')
        self.assertEqual(payroll.format_cents(123456), '$1,234.56')

    def test_rle(self):
        self.assertEqual(payroll.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(payroll.rle(''), [])
        self.assertEqual(payroll.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
