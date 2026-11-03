import unittest

from harbor.archive import rle
from harbor import archive


class Archive(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(rle(''), [])
        self.assertEqual(rle('abc'), [('a', 1), ('b', 1), ('c', 1)])

    def test_snake_case(self):
        self.assertEqual(archive.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(archive.snake_case('plain'), 'plain')
