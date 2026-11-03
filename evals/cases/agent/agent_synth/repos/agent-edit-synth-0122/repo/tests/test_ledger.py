import unittest

from harbor import ledger


class Ledger(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(ledger.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(ledger.luhn_valid('79927398713'), True)
        self.assertEqual(ledger.luhn_valid('79927398710'), False)

    def test_dedupe(self):
        self.assertEqual(ledger.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(ledger.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(ledger.dedupe([]), [])
