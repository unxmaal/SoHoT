import unittest

from harbor import ledger


class Ledger(unittest.TestCase):
    def test_cargo_row(self):
        self.assertEqual(ledger.cargo_row(95), {'cargo_row': 'A'})
        self.assertEqual(ledger.cargo_row(90), {'cargo_row': 'A'})

    def test_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])

    def test_moving_average(self):
        self.assertEqual(ledger.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(ledger.moving_average([5], 1), [5.0])
