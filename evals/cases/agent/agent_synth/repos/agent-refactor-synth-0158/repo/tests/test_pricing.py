import unittest

from atlas import pricing


class Pricing(unittest.TestCase):
    def test_dock_summary(self):
        self.assertEqual(pricing.dock_summary(2024), {'dock_summary': True})
        self.assertEqual(pricing.dock_summary(1900), {'dock_summary': False})

    def test_bucket(self):
        self.assertEqual(pricing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(pricing.bucket(-1, [0, 5, 10]), 0)

    def test_rle(self):
        self.assertEqual(pricing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(pricing.rle(''), [])
