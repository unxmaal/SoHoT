import unittest

from tally import budget


class Budget(unittest.TestCase):
    def test_tide_row(self):
        self.assertEqual(budget.tide_row('4539 1488 0343 6467'), {'tide_row': True})
        self.assertEqual(budget.tide_row('79927398713'), {'tide_row': True})

    def test_clamp(self):
        self.assertEqual(budget.clamp(5, 0, 10), 5)
        self.assertEqual(budget.clamp(-3, 0, 10), 0)

    def test_merge_ranges(self):
        self.assertEqual(budget.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(budget.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
