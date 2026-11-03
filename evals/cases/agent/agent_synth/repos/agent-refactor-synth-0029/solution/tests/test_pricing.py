import unittest

from granary.shared import bucket
from granary import pricing


class Pricing(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(bucket(5, [0, 5, 10]), 2)
        self.assertEqual(bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(bucket(12, [0, 5, 10]), 3)

    def test_clamp(self):
        self.assertEqual(pricing.clamp(5, 0, 10), 5)
        self.assertEqual(pricing.clamp(-3, 0, 10), 0)
