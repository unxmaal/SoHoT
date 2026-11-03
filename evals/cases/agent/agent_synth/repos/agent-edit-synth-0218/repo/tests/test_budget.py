import unittest

from depot import budget


class Budget(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(budget.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(budget.luhn_valid('79927398713'), True)
        self.assertEqual(budget.luhn_valid('79927398710'), False)

    def test_dedupe(self):
        self.assertEqual(budget.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(budget.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(budget.dedupe([]), [])
