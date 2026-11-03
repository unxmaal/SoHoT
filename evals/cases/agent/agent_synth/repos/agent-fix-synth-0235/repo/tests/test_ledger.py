import unittest

from foundry import ledger


class Ledger(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(ledger.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(ledger.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_moving_average(self):
        self.assertEqual(ledger.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(ledger.moving_average([5], 1), [5.0])

    def test_running_total(self):
        self.assertEqual(ledger.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(ledger.running_total([]), [])
