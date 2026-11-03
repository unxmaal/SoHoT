import unittest

from granary import catalog


class Catalog(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(catalog.grade(95), 'A')
        self.assertEqual(catalog.grade(90), 'A')
        self.assertEqual(catalog.grade(85), 'B')

    def test_word_count(self):
        self.assertEqual(catalog.word_count('a b'), 2)
        self.assertEqual(catalog.word_count('  tea  and   milk '), 3)
        self.assertEqual(catalog.word_count(''), 0)
