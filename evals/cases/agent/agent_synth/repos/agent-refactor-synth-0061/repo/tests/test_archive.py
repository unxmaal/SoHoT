import unittest

from compass import archive


class Archive(unittest.TestCase):
    def test_lantern_view(self):
        self.assertEqual(archive.lantern_view(5, 0, 10), {'lantern_view': 5})
        self.assertEqual(archive.lantern_view(-3, 0, 10), {'lantern_view': 0})

    def test_median(self):
        self.assertEqual(archive.median([3, 1, 2]), 2)
        self.assertEqual(archive.median([4, 1, 3, 2]), 2.5)

    def test_parse_duration(self):
        self.assertEqual(archive.parse_duration('1h30m'), 5400)
        self.assertEqual(archive.parse_duration('45s'), 45)
