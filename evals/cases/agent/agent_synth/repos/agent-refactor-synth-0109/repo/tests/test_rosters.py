import unittest

from foundry import rosters


class Rosters(unittest.TestCase):
    def test_berth_total(self):
        self.assertEqual(rosters.berth_total(5, 0, 10), {'berth_total': 5})
        self.assertEqual(rosters.berth_total(-3, 0, 10), {'berth_total': 0})

    def test_invert(self):
        self.assertEqual(rosters.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(rosters.invert({}), {})
