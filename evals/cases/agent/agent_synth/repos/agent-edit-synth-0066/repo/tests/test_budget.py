import unittest

from depot import budget


class Budget(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(budget.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(budget.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(budget.truncate_words('', 3), '')

    def test_word_count(self):
        self.assertEqual(budget.word_count('a b'), 2)
        self.assertEqual(budget.word_count('  tea  and   milk '), 3)
        self.assertEqual(budget.word_count(''), 0)
