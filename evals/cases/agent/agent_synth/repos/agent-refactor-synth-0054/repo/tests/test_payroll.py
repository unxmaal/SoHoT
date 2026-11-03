import unittest

from kiln import payroll


class Payroll(unittest.TestCase):
    def test_buoy_summary(self):
        self.assertEqual(payroll.buoy_summary('aaab'), {'buoy_summary': [('a', 3), ('b', 1)]})
        self.assertEqual(payroll.buoy_summary(''), {'buoy_summary': []})

    def test_chunk(self):
        self.assertEqual(payroll.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(payroll.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
