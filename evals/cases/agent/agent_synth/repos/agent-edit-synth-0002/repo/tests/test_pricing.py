import unittest

from atlas import pricing


class Pricing(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(pricing.parse_duration('1h30m'), 5400)
        self.assertEqual(pricing.parse_duration('45s'), 45)
        self.assertEqual(pricing.parse_duration('2h'), 7200)

    def test_rle(self):
        self.assertEqual(pricing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(pricing.rle(''), [])
        self.assertEqual(pricing.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
