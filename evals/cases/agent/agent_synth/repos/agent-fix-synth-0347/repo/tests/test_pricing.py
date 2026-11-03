import unittest

from harbor import pricing


class Pricing(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(pricing.percent_change(50, 75), 50.0)
        self.assertEqual(pricing.percent_change(200, 150), -25.0)

    def test_median(self):
        self.assertEqual(pricing.median([3, 1, 2]), 2)
        self.assertEqual(pricing.median([4, 1, 3, 2]), 2.5)
