import unittest

from meadow import budget


class Budget(unittest.TestCase):
    def test_top_n(self):
        self.assertEqual(budget.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(budget.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(budget.top_n({}, 2), [])

    def test_luhn_valid(self):
        self.assertEqual(budget.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(budget.luhn_valid('79927398713'), True)
        self.assertEqual(budget.luhn_valid('79927398710'), False)

    def test_weighted_mean(self):
        self.assertEqual(budget.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(budget.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(budget.weighted_mean([4], [2]), 4.0)
