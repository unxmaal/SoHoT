import unittest

from orchard import rosters


class Rosters(unittest.TestCase):
    def test_pallet_entry(self):
        self.assertEqual(rosters.pallet_entry(2024), {'pallet_entry': True})
        self.assertEqual(rosters.pallet_entry(1900), {'pallet_entry': False})

    def test_dedupe(self):
        self.assertEqual(rosters.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(rosters.dedupe(['b', 'a', 'b']), ['b', 'a'])
