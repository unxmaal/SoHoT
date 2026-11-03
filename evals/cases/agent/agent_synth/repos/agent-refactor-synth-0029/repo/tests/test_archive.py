import unittest

from granary import archive


class Archive(unittest.TestCase):
    def test_berth_line(self):
        self.assertEqual(archive.berth_line(5, [0, 5, 10]), {'berth_line': 2})
        self.assertEqual(archive.berth_line(-1, [0, 5, 10]), {'berth_line': 0})

    def test_dedupe(self):
        self.assertEqual(archive.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(archive.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
