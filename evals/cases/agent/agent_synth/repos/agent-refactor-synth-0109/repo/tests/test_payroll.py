import unittest

from foundry.payroll import clamp
from foundry import payroll


class Payroll(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-3, 0, 10), 0)
        self.assertEqual(clamp(15, 0, 10), 10)

    def test_is_leap(self):
        self.assertEqual(payroll.is_leap(2024), True)
        self.assertEqual(payroll.is_leap(1900), False)
