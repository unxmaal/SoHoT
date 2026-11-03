import unittest

from wharf import ledger


class Ledger(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)

    def test_dedupe(self):
        self.assertEqual(ledger.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(ledger.dedupe(['b', 'a', 'b']), ['b', 'a'])
