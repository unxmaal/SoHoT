import unittest

from wharf import pricing


class Pricing(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(pricing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(pricing.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_format_cents(self):
        self.assertEqual(pricing.format_cents(0), '$0.00')
        self.assertEqual(pricing.format_cents(123456), '$1,234.56')

    def test_percent_change(self):
        self.assertEqual(pricing.percent_change(50, 75), 50.0)
        self.assertEqual(pricing.percent_change(200, 150), -25.0)
