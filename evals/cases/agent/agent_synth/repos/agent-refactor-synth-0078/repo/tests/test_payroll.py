import unittest

from lantern import payroll


class Payroll(unittest.TestCase):
    def test_sail_entry(self):
        self.assertEqual(payroll.sail_entry([1, 2, 3, 4], 2), {'sail_entry': [1.5, 2.5, 3.5]})
        self.assertEqual(payroll.sail_entry([5], 1), {'sail_entry': [5.0]})

    def test_rle(self):
        self.assertEqual(payroll.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(payroll.rle(''), [])
