import unittest

from lantern import ledger


class Ledger(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(ledger.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(ledger.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(ledger.truncate_words('', 3), '')

    def test_weighted_mean(self):
        self.assertEqual(ledger.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(ledger.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(ledger.weighted_mean([4], [2]), 4.0)

    def test_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(ledger.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
