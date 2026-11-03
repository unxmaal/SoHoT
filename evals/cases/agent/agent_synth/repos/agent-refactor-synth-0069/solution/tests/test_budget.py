import unittest

from quarry.shared import luhn_valid
from quarry import budget


class Budget(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(luhn_valid('79927398713'), True)
        self.assertEqual(luhn_valid('79927398710'), False)

    def test_median(self):
        self.assertEqual(budget.median([3, 1, 2]), 2)
        self.assertEqual(budget.median([4, 1, 3, 2]), 2.5)
