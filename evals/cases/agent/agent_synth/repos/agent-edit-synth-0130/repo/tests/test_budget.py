import unittest

from tally import budget


class Budget(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(budget.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(budget.moving_average([5], 1), [5.0])
        self.assertEqual(budget.moving_average([1, 2, 3], 3), [2.0])

    def test_luhn_valid(self):
        self.assertEqual(budget.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(budget.luhn_valid('79927398713'), True)
        self.assertEqual(budget.luhn_valid('79927398710'), False)

    def test_rle(self):
        self.assertEqual(budget.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(budget.rle(''), [])
        self.assertEqual(budget.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
