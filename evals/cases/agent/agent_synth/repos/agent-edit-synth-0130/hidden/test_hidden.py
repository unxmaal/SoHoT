import unittest

from tally import budget
from tally import rosters
from tally import billing


class Hidden(unittest.TestCase):
    def test_budget_moving_average(self):
        self.assertEqual(budget.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(budget.moving_average([5], 1), [5.0])
        self.assertEqual(budget.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(budget.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            budget.moving_average([1, 2], 0)

    def test_budget_luhn_valid(self):
        self.assertEqual(budget.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(budget.luhn_valid('79927398713'), True)
        self.assertEqual(budget.luhn_valid('79927398710'), False)
        self.assertEqual(budget.luhn_valid(''), False)
        self.assertEqual(budget.luhn_valid('059'), True)

    def test_budget_rle(self):
        self.assertEqual(budget.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(budget.rle(''), [])
        self.assertEqual(budget.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(budget.rle('zz'), [('z', 2)])

    def test_rosters_merge_ranges(self):
        self.assertEqual(rosters.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(rosters.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(rosters.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(rosters.merge_ranges([]), [])
        self.assertEqual(rosters.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_rosters_percent_change(self):
        self.assertEqual(rosters.percent_change(50, 75), 50.0)
        self.assertEqual(rosters.percent_change(200, 150), -25.0)
        self.assertEqual(rosters.percent_change(80, 80), 0.0)
        self.assertEqual(rosters.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            rosters.percent_change(0, 5)
        self.assertEqual(rosters.percent_change(-10, -5), -50.0)

    def test_rosters_dedupe(self):
        self.assertEqual(rosters.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(rosters.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(rosters.dedupe([]), [])
        self.assertEqual(rosters.dedupe([1, 1, 1]), [1])

    def test_billing_word_count(self):
        self.assertEqual(billing.word_count('a b'), 2)
        self.assertEqual(billing.word_count('  tea  and   milk '), 3)
        self.assertEqual(billing.word_count(''), 0)
        self.assertEqual(billing.word_count('one'), 1)

    def test_billing_running_total(self):
        self.assertEqual(billing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(billing.running_total([]), [])
        self.assertEqual(billing.running_total([5]), [5])
        self.assertEqual(billing.running_total([2, -2, 2]), [2, 0, 2])

    def test_feature(self):
        self.assertEqual(billing.running_total([1, 2], start=10), [11, 13])
        self.assertEqual(billing.running_total([], start=4), [])
        self.assertEqual(billing.running_total([3], start=-3), [0])
