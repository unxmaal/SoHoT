import unittest

from atlas import archive


class Archive(unittest.TestCase):
    def test_barge_line(self):
        self.assertEqual(archive.barge_line({'a': 1, 'b': 2, 'c': 1}), {'barge_line': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(archive.barge_line({}), {'barge_line': {}})

    def test_bucket(self):
        self.assertEqual(archive.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(archive.bucket(-1, [0, 5, 10]), 0)

    def test_clamp(self):
        self.assertEqual(archive.clamp(5, 0, 10), 5)
        self.assertEqual(archive.clamp(-3, 0, 10), 0)
