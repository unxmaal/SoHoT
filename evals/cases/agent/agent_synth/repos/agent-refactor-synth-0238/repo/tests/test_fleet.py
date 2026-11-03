import unittest

from orchard import fleet


class Fleet(unittest.TestCase):
    def test_crate_entry(self):
        self.assertEqual(fleet.crate_entry([3, 1, 3, 2, 1]), {'crate_entry': [3, 1, 2]})
        self.assertEqual(fleet.crate_entry(['b', 'a', 'b']), {'crate_entry': ['b', 'a']})

    def test_rle(self):
        self.assertEqual(fleet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(fleet.rle(''), [])
