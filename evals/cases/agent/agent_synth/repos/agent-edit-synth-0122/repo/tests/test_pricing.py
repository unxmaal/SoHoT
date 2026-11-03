import unittest

from harbor import pricing


class Pricing(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(pricing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(pricing.rle(''), [])
        self.assertEqual(pricing.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])

    def test_grade(self):
        self.assertEqual(pricing.grade(95), 'A')
        self.assertEqual(pricing.grade(90), 'A')
        self.assertEqual(pricing.grade(85), 'B')

    def test_parse_duration(self):
        self.assertEqual(pricing.parse_duration('1h30m'), 5400)
        self.assertEqual(pricing.parse_duration('45s'), 45)
        self.assertEqual(pricing.parse_duration('2h'), 7200)
