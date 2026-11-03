import unittest

from depot import ledger


class Ledger(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)

    def test_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
