import unittest

from orchard.rosters import bound


class Rosters(unittest.TestCase):
    def test_bound(self):
        self.assertEqual(bound(5, 0, 10), 5)
        self.assertEqual(bound(-3, 0, 10), 0)
        self.assertEqual(bound(15, 0, 10), 10)
