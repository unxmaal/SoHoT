import unittest

from granary import payroll


class Payroll(unittest.TestCase):
    def test_berth_view(self):
        self.assertEqual(payroll.berth_view('the quick brown fox', 2), {'berth_view': 'the quick...'})
        self.assertEqual(payroll.berth_view('tea time', 2), {'berth_view': 'tea time'})

    def test_paginate(self):
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_rle(self):
        self.assertEqual(payroll.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(payroll.rle(''), [])
