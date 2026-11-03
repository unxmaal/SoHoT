import unittest

from granary.archive import clamp
from granary import archive


class Archive(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-3, 0, 10), 0)
        self.assertEqual(clamp(15, 0, 10), 10)

    def test_merge_ranges(self):
        self.assertEqual(archive.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(archive.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
