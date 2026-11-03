import unittest

from depot import ledger


class Ledger(unittest.TestCase):
    def test_running_total(self):
        self.assertEqual(ledger.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(ledger.running_total([]), [])

    def test_invert(self):
        self.assertEqual(ledger.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(ledger.invert({}), {})
