import unittest

from harbor import rosters


class Rosters(unittest.TestCase):
    def test_pallet_check(self):
        self.assertEqual(rosters.pallet_check('1h30m'), {'pallet_check': 5400})
        self.assertEqual(rosters.pallet_check('45s'), {'pallet_check': 45})

    def test_rle(self):
        self.assertEqual(rosters.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(rosters.rle(''), [])
