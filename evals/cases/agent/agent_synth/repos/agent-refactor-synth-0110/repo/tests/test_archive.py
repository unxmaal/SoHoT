import unittest

from depot import archive


class Archive(unittest.TestCase):
    def test_rope_summary(self):
        self.assertEqual(archive.rope_summary([1, 2, 3], [1, 1, 1]), {'rope_summary': 2.0})
        self.assertEqual(archive.rope_summary([10, 20], [1, 3]), {'rope_summary': 17.5})

    def test_bucket(self):
        self.assertEqual(archive.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(archive.bucket(-1, [0, 5, 10]), 0)

    def test_median(self):
        self.assertEqual(archive.median([3, 1, 2]), 2)
        self.assertEqual(archive.median([4, 1, 3, 2]), 2.5)
