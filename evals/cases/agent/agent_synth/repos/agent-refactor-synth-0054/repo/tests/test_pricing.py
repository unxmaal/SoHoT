import unittest

from kiln.pricing import rle


class Pricing(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(rle(''), [])
        self.assertEqual(rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
