import unittest

from mill import payroll


class Payroll(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_percent_change(self):
        self.assertEqual(payroll.percent_change(50, 75), 50.0)
        self.assertEqual(payroll.percent_change(200, 150), -25.0)
