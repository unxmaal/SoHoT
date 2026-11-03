import unittest

from granary import payroll


class Payroll(unittest.TestCase):
    def test_hull_summary(self):
        self.assertEqual(payroll.hull_summary([1, 2, 3, 4], 2), {'hull_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(payroll.hull_summary([5], 1), {'hull_summary': [5.0]})

    def test_chunk(self):
        self.assertEqual(payroll.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(payroll.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_weighted_mean(self):
        self.assertEqual(payroll.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(payroll.weighted_mean([10, 20], [1, 3]), 17.5)
