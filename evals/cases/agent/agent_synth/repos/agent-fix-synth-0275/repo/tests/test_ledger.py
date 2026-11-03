import unittest

from harbor import ledger


class Ledger(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(ledger.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_weighted_mean(self):
        self.assertEqual(ledger.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(ledger.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)
