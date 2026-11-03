import unittest

from wharf import archive


class Archive(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])

    def test_clamp(self):
        self.assertEqual(archive.clamp(5, 0, 10), 5)
        self.assertEqual(archive.clamp(-3, 0, 10), 0)

    def test_dedupe(self):
        self.assertEqual(archive.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(archive.dedupe(['b', 'a', 'b']), ['b', 'a'])
