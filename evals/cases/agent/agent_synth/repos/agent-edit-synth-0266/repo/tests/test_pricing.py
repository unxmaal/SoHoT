import unittest

from atlas import pricing


class Pricing(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(pricing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(pricing.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(pricing.bucket(12, [0, 5, 10]), 3)

    def test_invert(self):
        self.assertEqual(pricing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(pricing.invert({}), {})
        self.assertEqual(pricing.invert({'x': 'y'}), {'y': ['x']})

    def test_format_cents(self):
        self.assertEqual(pricing.format_cents(0), '$0.00')
        self.assertEqual(pricing.format_cents(123456), '$1,234.56')
        self.assertEqual(pricing.format_cents(-105), '-$1.05')
