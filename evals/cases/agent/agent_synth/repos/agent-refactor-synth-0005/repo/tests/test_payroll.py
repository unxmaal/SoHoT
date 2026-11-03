import unittest

from mill.payroll import format_cents
from mill import payroll


class Payroll(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(format_cents(0), '$0.00')
        self.assertEqual(format_cents(123456), '$1,234.56')
        self.assertEqual(format_cents(-105), '-$1.05')

    def test_truncate_words(self):
        self.assertEqual(payroll.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(payroll.truncate_words('tea time', 2), 'tea time')
