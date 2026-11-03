import unittest

from quarry import pricing


class Pricing(unittest.TestCase):
    def test_anchor_summary(self):
        self.assertEqual(pricing.anchor_summary([1, 2, 3]), {'anchor_summary': [1, 3, 6]})
        self.assertEqual(pricing.anchor_summary([]), {'anchor_summary': []})

    def test_dedupe(self):
        self.assertEqual(pricing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(pricing.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_percent_change(self):
        self.assertEqual(pricing.percent_change(50, 75), 50.0)
        self.assertEqual(pricing.percent_change(200, 150), -25.0)
