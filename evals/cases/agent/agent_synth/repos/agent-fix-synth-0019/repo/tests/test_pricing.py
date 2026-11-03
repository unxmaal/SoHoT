import unittest

from wharf import pricing


class Pricing(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(pricing.parse_duration('1h30m'), 5400)
        self.assertEqual(pricing.parse_duration('45s'), 45)

    def test_moving_average(self):
        self.assertEqual(pricing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(pricing.moving_average([5], 1), [5.0])
