import unittest

from quarry import archive


class Archive(unittest.TestCase):
    def test_running_total(self):
        self.assertEqual(archive.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(archive.running_total([]), [])
        self.assertEqual(archive.running_total([5]), [5])

    def test_chunk(self):
        self.assertEqual(archive.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(archive.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(archive.chunk([], 3), [])

    def test_truncate_words(self):
        self.assertEqual(archive.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(archive.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(archive.truncate_words('', 3), '')
