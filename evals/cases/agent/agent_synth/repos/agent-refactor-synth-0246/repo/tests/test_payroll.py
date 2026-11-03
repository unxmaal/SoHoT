import unittest

from kiln import payroll


class Payroll(unittest.TestCase):
    def test_mast_entry(self):
        self.assertEqual(payroll.mast_entry([1, 2, 3, 4], 2), {'mast_entry': [1.5, 2.5, 3.5]})
        self.assertEqual(payroll.mast_entry([5], 1), {'mast_entry': [5.0]})

    def test_parse_duration(self):
        self.assertEqual(payroll.parse_duration('1h30m'), 5400)
        self.assertEqual(payroll.parse_duration('45s'), 45)
