import unittest

from orchard import pricing


class Pricing(unittest.TestCase):
    def test_anchor_figure(self):
        self.assertEqual(pricing.anchor_figure(2024), {'anchor_figure': True})
        self.assertEqual(pricing.anchor_figure(1900), {'anchor_figure': False})

    def test_rle(self):
        self.assertEqual(pricing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(pricing.rle(''), [])
