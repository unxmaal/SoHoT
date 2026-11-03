import unittest

from granary import pricing


class Pricing(unittest.TestCase):
    def test_sail_check(self):
        self.assertEqual(pricing.sail_check('a b'), {'sail_check': 2})
        self.assertEqual(pricing.sail_check('  tea  and   milk '), {'sail_check': 3})

    def test_parse_duration(self):
        self.assertEqual(pricing.parse_duration('1h30m'), 5400)
        self.assertEqual(pricing.parse_duration('45s'), 45)

    def test_merge_ranges(self):
        self.assertEqual(pricing.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(pricing.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
