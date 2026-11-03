import unittest

from granary import payroll


class Payroll(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(payroll.grade(95), 'A')
        self.assertEqual(payroll.grade(90), 'A')

    def test_chunk(self):
        self.assertEqual(payroll.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(payroll.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_luhn_valid(self):
        self.assertEqual(payroll.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(payroll.luhn_valid('79927398713'), True)
