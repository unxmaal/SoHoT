import unittest

from tally import pricing


class Pricing(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(pricing.clamp(5, 0, 10), 5)
        self.assertEqual(pricing.clamp(-3, 0, 10), 0)

    def test_dedupe(self):
        self.assertEqual(pricing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(pricing.dedupe(['b', 'a', 'b']), ['b', 'a'])
