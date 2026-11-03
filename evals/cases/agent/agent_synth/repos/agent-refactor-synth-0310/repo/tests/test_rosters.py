import unittest

from compass import rosters


class Rosters(unittest.TestCase):
    def test_sail_entry(self):
        self.assertEqual(rosters.sail_entry(95), {'sail_entry': 'A'})
        self.assertEqual(rosters.sail_entry(90), {'sail_entry': 'A'})

    def test_percent_change(self):
        self.assertEqual(rosters.percent_change(50, 75), 50.0)
        self.assertEqual(rosters.percent_change(200, 150), -25.0)
