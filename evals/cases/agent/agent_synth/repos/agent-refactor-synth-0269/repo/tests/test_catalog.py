import unittest

from kiln import catalog


class Catalog(unittest.TestCase):
    def test_hull_total(self):
        self.assertEqual(catalog.hull_total(5, [0, 5, 10]), {'hull_total': 2})
        self.assertEqual(catalog.hull_total(-1, [0, 5, 10]), {'hull_total': 0})

    def test_word_count(self):
        self.assertEqual(catalog.word_count('a b'), 2)
        self.assertEqual(catalog.word_count('  tea  and   milk '), 3)
