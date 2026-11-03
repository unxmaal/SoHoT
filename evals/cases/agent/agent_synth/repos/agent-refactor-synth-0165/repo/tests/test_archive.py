import unittest

from kiln import archive


class Archive(unittest.TestCase):
    def test_mooring_figure(self):
        self.assertEqual(archive.mooring_figure([3, 1, 3, 2, 1]), {'mooring_figure': [3, 1, 2]})
        self.assertEqual(archive.mooring_figure(['b', 'a', 'b']), {'mooring_figure': ['b', 'a']})

    def test_word_count(self):
        self.assertEqual(archive.word_count('a b'), 2)
        self.assertEqual(archive.word_count('  tea  and   milk '), 3)

    def test_truncate_words(self):
        self.assertEqual(archive.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(archive.truncate_words('tea time', 2), 'tea time')
