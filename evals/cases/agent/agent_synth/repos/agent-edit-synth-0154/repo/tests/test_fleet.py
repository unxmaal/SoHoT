import unittest

from depot import fleet


class Fleet(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(fleet.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(fleet.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(fleet.chunk([], 3), [])

    def test_grade(self):
        self.assertEqual(fleet.grade(95), 'A')
        self.assertEqual(fleet.grade(90), 'A')
        self.assertEqual(fleet.grade(85), 'B')

    def test_rle(self):
        self.assertEqual(fleet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(fleet.rle(''), [])
        self.assertEqual(fleet.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
