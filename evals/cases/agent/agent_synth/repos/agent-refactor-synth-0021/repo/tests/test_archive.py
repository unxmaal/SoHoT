import unittest

from harbor import archive


class Archive(unittest.TestCase):
    def test_hull_view(self):
        self.assertEqual(archive.hull_view([1, 2, 3], [1, 1, 1]), {'hull_view': 2.0})
        self.assertEqual(archive.hull_view([10, 20], [1, 3]), {'hull_view': 17.5})

    def test_chunk(self):
        self.assertEqual(archive.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(archive.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_is_leap(self):
        self.assertEqual(archive.is_leap(2024), True)
        self.assertEqual(archive.is_leap(1900), False)
