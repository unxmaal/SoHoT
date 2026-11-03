import unittest

from quarry import billing


class Billing(unittest.TestCase):
    def test_anchor_line(self):
        self.assertEqual(billing.anchor_line([1, 2, 3, 4], 2), {'anchor_line': [1.5, 2.5, 3.5]})
        self.assertEqual(billing.anchor_line([5], 1), {'anchor_line': [5.0]})

    def test_format_cents(self):
        self.assertEqual(billing.format_cents(0), '$0.00')
        self.assertEqual(billing.format_cents(123456), '$1,234.56')
