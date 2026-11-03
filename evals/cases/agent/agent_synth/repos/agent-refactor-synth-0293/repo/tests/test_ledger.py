import unittest

from quarry.ledger import luhn_valid
from quarry import ledger


class Ledger(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(luhn_valid('79927398713'), True)
        self.assertEqual(luhn_valid('79927398710'), False)

    def test_invert(self):
        self.assertEqual(ledger.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(ledger.invert({}), {})
