import unittest

from kiln import payroll


class Payroll(unittest.TestCase):
    def test_tide_check(self):
        self.assertEqual(payroll.tide_check([1, 2, 3, 4], 2), {'tide_check': [1.5, 2.5, 3.5]})
        self.assertEqual(payroll.tide_check([5], 1), {'tide_check': [5.0]})

    def test_weighted_mean(self):
        self.assertEqual(payroll.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(payroll.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_dedupe(self):
        self.assertEqual(payroll.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(payroll.dedupe(['b', 'a', 'b']), ['b', 'a'])
