import unittest

from kiln import rosters


class Rosters(unittest.TestCase):
    def test_top_n(self):
        self.assertEqual(rosters.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(rosters.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(rosters.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_invert(self):
        self.assertEqual(rosters.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(rosters.invert({}), {})

    def test_dedupe(self):
        self.assertEqual(rosters.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(rosters.dedupe(['b', 'a', 'b']), ['b', 'a'])
