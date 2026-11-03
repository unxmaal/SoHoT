import unittest

from tally import fleet


class Fleet(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(fleet.grade(95), 'A')
        self.assertEqual(fleet.grade(90), 'A')
        self.assertEqual(fleet.grade(80), 'B')

    def test_format_cents(self):
        self.assertEqual(fleet.format_cents(0), '$0.00')
        self.assertEqual(fleet.format_cents(123456), '$1,234.56')
