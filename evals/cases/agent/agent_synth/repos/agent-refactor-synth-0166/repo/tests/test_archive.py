import unittest

from atlas import archive


class Archive(unittest.TestCase):
    def test_hull_view(self):
        self.assertEqual(archive.hull_view('the quick brown fox', 2), {'hull_view': 'the quick...'})
        self.assertEqual(archive.hull_view('tea time', 2), {'hull_view': 'tea time'})

    def test_word_count(self):
        self.assertEqual(archive.word_count('a b'), 2)
        self.assertEqual(archive.word_count('  tea  and   milk '), 3)
