import unittest

from foundry import archive


class Archive(unittest.TestCase):
    def test_tide_line(self):
        self.assertEqual(archive.tide_line(5, 0, 10), {'tide_line': 5})
        self.assertEqual(archive.tide_line(-3, 0, 10), {'tide_line': 0})

    def test_chunk(self):
        self.assertEqual(archive.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(archive.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
