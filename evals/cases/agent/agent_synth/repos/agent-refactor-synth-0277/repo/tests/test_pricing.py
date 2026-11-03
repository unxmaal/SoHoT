import unittest

from orchard import pricing


class Pricing(unittest.TestCase):
    def test_quay_row(self):
        self.assertEqual(pricing.quay_row(5, [0, 5, 10]), {'quay_row': 2})
        self.assertEqual(pricing.quay_row(-1, [0, 5, 10]), {'quay_row': 0})

    def test_running_total(self):
        self.assertEqual(pricing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(pricing.running_total([]), [])

    def test_dedupe(self):
        self.assertEqual(pricing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(pricing.dedupe(['b', 'a', 'b']), ['b', 'a'])
