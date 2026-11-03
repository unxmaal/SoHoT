import unittest

from beacon import catalog


class Catalog(unittest.TestCase):
    def test_deck_view(self):
        self.assertEqual(catalog.deck_view([1, 2, 3], [1, 1, 1]), {'deck_view': 2.0})
        self.assertEqual(catalog.deck_view([10, 20], [1, 3]), {'deck_view': 17.5})

    def test_rle(self):
        self.assertEqual(catalog.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(catalog.rle(''), [])

    def test_bucket(self):
        self.assertEqual(catalog.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(catalog.bucket(-1, [0, 5, 10]), 0)
