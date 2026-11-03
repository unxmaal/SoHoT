import unittest

from beacon.fleet import drop_repeats
from beacon import fleet


class Fleet(unittest.TestCase):
    def test_drop_repeats(self):
        self.assertEqual(drop_repeats([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(drop_repeats(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(drop_repeats([]), [])

    def test_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
