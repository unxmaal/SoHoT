import unittest

from atlas import ledger


class Ledger(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(ledger.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(ledger.rle(''), [])
        self.assertEqual(ledger.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])

    def test_moving_average(self):
        self.assertEqual(ledger.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(ledger.moving_average([5], 1), [5.0])
        self.assertEqual(ledger.moving_average([1, 2, 3], 3), [2.0])
