import unittest

from granary import payroll


class Payroll(unittest.TestCase):
    def test_anchor_summary(self):
        self.assertEqual(payroll.anchor_summary([(1, 3), (3, 5)]), {'anchor_summary': [(1, 5)]})
        self.assertEqual(payroll.anchor_summary([(5, 6), (1, 2)]), {'anchor_summary': [(1, 2), (5, 6)]})

    def test_paginate(self):
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
