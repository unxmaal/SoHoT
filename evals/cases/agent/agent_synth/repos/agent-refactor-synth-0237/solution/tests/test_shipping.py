import unittest

from wharf.tools import format_cents
from wharf import shipping


class Shipping(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(format_cents(0), '$0.00')
        self.assertEqual(format_cents(123456), '$1,234.56')
        self.assertEqual(format_cents(-105), '-$1.05')

    def test_parse_duration(self):
        self.assertEqual(shipping.parse_duration('1h30m'), 5400)
        self.assertEqual(shipping.parse_duration('45s'), 45)
