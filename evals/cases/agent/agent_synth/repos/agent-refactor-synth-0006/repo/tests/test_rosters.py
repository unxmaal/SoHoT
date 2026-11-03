import unittest

from lantern import rosters


class Rosters(unittest.TestCase):
    def test_tide_row(self):
        self.assertEqual(rosters.tide_row([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), {'tide_row': [1, 2, 3]})
        self.assertEqual(rosters.tide_row([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), {'tide_row': [10]})

    def test_format_cents(self):
        self.assertEqual(rosters.format_cents(0), '$0.00')
        self.assertEqual(rosters.format_cents(123456), '$1,234.56')
