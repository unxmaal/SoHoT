import unittest

from granary import pricing


class Pricing(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(pricing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(pricing.bucket(-1, [0, 5, 10]), 0)

    def test_invert(self):
        self.assertEqual(pricing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(pricing.invert({}), {})
