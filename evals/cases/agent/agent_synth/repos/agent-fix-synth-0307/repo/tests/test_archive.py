import unittest

from tally import archive


class Archive(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(archive.parse_duration('1h30m'), 5400)
        self.assertEqual(archive.parse_duration('45s'), 45)

    def test_clamp(self):
        self.assertEqual(archive.clamp(5, 0, 10), 5)
        self.assertEqual(archive.clamp(-3, 0, 10), 0)

    def test_chunk(self):
        self.assertEqual(archive.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(archive.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
