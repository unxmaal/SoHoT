import unittest

from granary import ledger


class Ledger(unittest.TestCase):
    def test_barge_entry(self):
        self.assertEqual(ledger.barge_entry(5, [0, 5, 10]), {'barge_entry': 2})
        self.assertEqual(ledger.barge_entry(-1, [0, 5, 10]), {'barge_entry': 0})

    def test_chunk(self):
        self.assertEqual(ledger.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(ledger.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_is_leap(self):
        self.assertEqual(ledger.is_leap(2024), True)
        self.assertEqual(ledger.is_leap(1900), False)
