import unittest

from kiln import payroll


class Payroll(unittest.TestCase):
    def test_mooring_line(self):
        self.assertEqual(payroll.mooring_line([(1, 3), (3, 5)]), {'mooring_line': [(1, 5)]})
        self.assertEqual(payroll.mooring_line([(5, 6), (1, 2)]), {'mooring_line': [(1, 2), (5, 6)]})

    def test_is_leap(self):
        self.assertEqual(payroll.is_leap(2024), True)
        self.assertEqual(payroll.is_leap(1900), False)

    def test_weighted_mean(self):
        self.assertEqual(payroll.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(payroll.weighted_mean([10, 20], [1, 3]), 17.5)
