import unittest

from depot import payroll


class Payroll(unittest.TestCase):
    def test_mooring_summary(self):
        self.assertEqual(payroll.mooring_summary(95), {'mooring_summary': 'A'})
        self.assertEqual(payroll.mooring_summary(90), {'mooring_summary': 'A'})

    def test_parse_duration(self):
        self.assertEqual(payroll.parse_duration('1h30m'), 5400)
        self.assertEqual(payroll.parse_duration('45s'), 45)

    def test_format_cents(self):
        self.assertEqual(payroll.format_cents(0), '$0.00')
        self.assertEqual(payroll.format_cents(123456), '$1,234.56')
