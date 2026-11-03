import unittest

from foundry import ledger


class Ledger(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(ledger.word_count('a b'), 2)
        self.assertEqual(ledger.word_count('  tea  and   milk '), 3)
        self.assertEqual(ledger.word_count(''), 0)

    def test_median(self):
        self.assertEqual(ledger.median([3, 1, 2]), 2)
        self.assertEqual(ledger.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(ledger.median([5]), 5)

    def test_truncate_words(self):
        self.assertEqual(ledger.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(ledger.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(ledger.truncate_words('', 3), '')
