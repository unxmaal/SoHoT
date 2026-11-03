import unittest

from tally import shipping


class Shipping(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(shipping.percent_change(50, 75), 50.0)
        self.assertEqual(shipping.percent_change(200, 150), -25.0)

    def test_format_cents(self):
        self.assertEqual(shipping.format_cents(0), '$0.00')
        self.assertEqual(shipping.format_cents(123456), '$1,234.56')
