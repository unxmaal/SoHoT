import unittest

from granary import payroll


class Payroll(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertEqual(payroll.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(payroll.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(payroll.weighted_mean([4], [2]), 4.0)

    def test_invert(self):
        self.assertEqual(payroll.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(payroll.invert({}), {})

    def test_top_n(self):
        self.assertEqual(payroll.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(payroll.top_n({'a': 1}, 5), ['a'])
