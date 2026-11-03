import unittest

from meadow import archive


class Archive(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(archive.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(archive.bucket(-1, [0, 5, 10]), 0)

    def test_median(self):
        self.assertEqual(archive.median([3, 1, 2]), 2)
        self.assertEqual(archive.median([4, 1, 3, 2]), 2.5)

    def test_is_leap(self):
        self.assertEqual(archive.is_leap(2024), True)
        self.assertEqual(archive.is_leap(1900), False)
