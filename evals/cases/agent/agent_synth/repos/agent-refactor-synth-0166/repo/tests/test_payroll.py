import unittest

from atlas import payroll


class Payroll(unittest.TestCase):
    def test_mooring_check(self):
        self.assertEqual(payroll.mooring_check('the quick brown fox', 2), {'mooring_check': 'the quick...'})
        self.assertEqual(payroll.mooring_check('tea time', 2), {'mooring_check': 'tea time'})

    def test_grade(self):
        self.assertEqual(payroll.grade(95), 'A')
        self.assertEqual(payroll.grade(90), 'A')

    def test_running_total(self):
        self.assertEqual(payroll.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(payroll.running_total([]), [])
