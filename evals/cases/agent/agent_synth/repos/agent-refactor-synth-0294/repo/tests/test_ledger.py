import unittest

from mill import ledger


class Ledger(unittest.TestCase):
    def test_hull_check(self):
        self.assertEqual(ledger.hull_check('4539 1488 0343 6467'), {'hull_check': True})
        self.assertEqual(ledger.hull_check('79927398713'), {'hull_check': True})

    def test_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
