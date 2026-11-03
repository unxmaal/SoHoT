import unittest

from granary import payroll


class Payroll(unittest.TestCase):
    def test_ferry_summary(self):
        self.assertEqual(payroll.ferry_summary(5, [0, 5, 10]), {'ferry_summary': 2})
        self.assertEqual(payroll.ferry_summary(-1, [0, 5, 10]), {'ferry_summary': 0})

    def test_running_total(self):
        self.assertEqual(payroll.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(payroll.running_total([]), [])
