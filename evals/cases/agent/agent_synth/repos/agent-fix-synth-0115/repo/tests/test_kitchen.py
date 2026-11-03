import unittest

from depot import kitchen


class Kitchen(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(kitchen.grade(95), 'A')
        self.assertEqual(kitchen.grade(90), 'A')
        self.assertEqual(kitchen.grade(80), 'B')

    def test_luhn_valid(self):
        self.assertEqual(kitchen.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(kitchen.luhn_valid('79927398713'), True)

    def test_format_cents(self):
        self.assertEqual(kitchen.format_cents(0), '$0.00')
        self.assertEqual(kitchen.format_cents(123456), '$1,234.56')
