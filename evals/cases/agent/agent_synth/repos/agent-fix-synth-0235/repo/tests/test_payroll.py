import unittest

from foundry import payroll


class Payroll(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(payroll.grade(95), 'A')
        self.assertEqual(payroll.grade(90), 'A')
        self.assertEqual(payroll.grade(80), 'B')

    def test_median(self):
        self.assertEqual(payroll.median([3, 1, 2]), 2)
        self.assertEqual(payroll.median([4, 1, 3, 2]), 2.5)
