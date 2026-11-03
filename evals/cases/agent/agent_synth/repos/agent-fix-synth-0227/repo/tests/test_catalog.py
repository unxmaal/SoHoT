import unittest

from lantern import catalog


class Catalog(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(catalog.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(catalog.rle(''), [])

    def test_moving_average(self):
        self.assertEqual(catalog.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(catalog.moving_average([5], 1), [5.0])
        self.assertEqual(catalog.moving_average([1, 2, 3], 3), [2.0])
