import unittest

from orchard import pricing


class Pricing(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(pricing.is_leap(2024), True)
        self.assertEqual(pricing.is_leap(1900), False)
        self.assertEqual(pricing.is_leap(2000), True)

    def test_grade(self):
        self.assertEqual(pricing.grade(95), 'A')
        self.assertEqual(pricing.grade(90), 'A')
        self.assertEqual(pricing.grade(85), 'B')

    def test_format_cents(self):
        self.assertEqual(pricing.format_cents(0), '$0.00')
        self.assertEqual(pricing.format_cents(123456), '$1,234.56')
        self.assertEqual(pricing.format_cents(-105), '-$1.05')
