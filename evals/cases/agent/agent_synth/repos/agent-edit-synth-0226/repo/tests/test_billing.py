import unittest

from mill import billing


class Billing(unittest.TestCase):
    def test_running_total(self):
        self.assertEqual(billing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(billing.running_total([]), [])
        self.assertEqual(billing.running_total([5]), [5])

    def test_paginate(self):
        self.assertEqual(billing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(billing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(billing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])

    def test_merge_ranges(self):
        self.assertEqual(billing.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(billing.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(billing.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
