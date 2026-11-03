import unittest

from compass import rosters


class Rosters(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(rosters.is_leap(2024), True)
        self.assertEqual(rosters.is_leap(1900), False)
        self.assertEqual(rosters.is_leap(2000), True)

    def test_format_cents(self):
        self.assertEqual(rosters.format_cents(0), '$0.00')
        self.assertEqual(rosters.format_cents(123456), '$1,234.56')
        self.assertEqual(rosters.format_cents(-105), '-$1.05')

    def test_invert(self):
        self.assertEqual(rosters.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(rosters.invert({}), {})
        self.assertEqual(rosters.invert({'x': 'y'}), {'y': ['x']})
