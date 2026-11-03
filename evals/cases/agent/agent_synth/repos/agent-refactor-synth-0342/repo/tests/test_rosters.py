import unittest

from quarry import rosters


class Rosters(unittest.TestCase):
    def test_quay_view(self):
        self.assertEqual(rosters.quay_view(0), {'quay_view': '$0.00'})
        self.assertEqual(rosters.quay_view(123456), {'quay_view': '$1,234.56'})

    def test_is_leap(self):
        self.assertEqual(rosters.is_leap(2024), True)
        self.assertEqual(rosters.is_leap(1900), False)
