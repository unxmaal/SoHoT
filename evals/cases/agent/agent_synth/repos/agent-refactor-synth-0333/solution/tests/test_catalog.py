import unittest

from foundry.tools import dedupe
from foundry import catalog


class Catalog(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(dedupe([]), [])

    def test_rle(self):
        self.assertEqual(catalog.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(catalog.rle(''), [])
