import unittest

from beacon import kitchen


class Kitchen(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(kitchen.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(kitchen.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(kitchen.dedupe([]), [])

    def test_chunk(self):
        self.assertEqual(kitchen.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(kitchen.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(kitchen.chunk([], 3), [])

    def test_rle(self):
        self.assertEqual(kitchen.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(kitchen.rle(''), [])
        self.assertEqual(kitchen.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
