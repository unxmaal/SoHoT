import unittest

from kiln import archive


class Archive(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(archive.clamp(5, 0, 10), 5)
        self.assertEqual(archive.clamp(-3, 0, 10), 0)

    def test_parse_duration(self):
        self.assertEqual(archive.parse_duration('1h30m'), 5400)
        self.assertEqual(archive.parse_duration('45s'), 45)

    def test_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)
