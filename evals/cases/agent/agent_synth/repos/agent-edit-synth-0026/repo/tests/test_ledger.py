import unittest

from quarry import ledger


class Ledger(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(ledger.word_count('a b'), 2)
        self.assertEqual(ledger.word_count('  tea  and   milk '), 3)
        self.assertEqual(ledger.word_count(''), 0)

    def test_grade(self):
        self.assertEqual(ledger.grade(95), 'A')
        self.assertEqual(ledger.grade(90), 'A')
        self.assertEqual(ledger.grade(85), 'B')

    def test_parse_duration(self):
        self.assertEqual(ledger.parse_duration('1h30m'), 5400)
        self.assertEqual(ledger.parse_duration('45s'), 45)
        self.assertEqual(ledger.parse_duration('2h'), 7200)
