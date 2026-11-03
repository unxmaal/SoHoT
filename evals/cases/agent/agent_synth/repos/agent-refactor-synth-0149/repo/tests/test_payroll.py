import unittest

from compass import payroll


class Payroll(unittest.TestCase):
    def test_harbor_line(self):
        self.assertEqual(payroll.harbor_line([(1, 3), (3, 5)]), {'harbor_line': [(1, 5)]})
        self.assertEqual(payroll.harbor_line([(5, 6), (1, 2)]), {'harbor_line': [(1, 2), (5, 6)]})

    def test_clamp(self):
        self.assertEqual(payroll.clamp(5, 0, 10), 5)
        self.assertEqual(payroll.clamp(-3, 0, 10), 0)
