import unittest

from foundry.rosters import clamp
from foundry import rosters


class Rosters(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-3, 0, 10), 0)
        self.assertEqual(clamp(15, 0, 10), 10)

    def test_dedupe(self):
        self.assertEqual(rosters.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(rosters.dedupe(['b', 'a', 'b']), ['b', 'a'])
