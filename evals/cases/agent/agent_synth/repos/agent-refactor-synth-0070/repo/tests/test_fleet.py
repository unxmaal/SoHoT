import unittest

from beacon.fleet import dedupe
from beacon import fleet


class Fleet(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(dedupe([]), [])

    def test_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
