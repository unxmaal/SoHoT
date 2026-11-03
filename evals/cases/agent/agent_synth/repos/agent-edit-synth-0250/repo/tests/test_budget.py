import unittest

from wharf import budget


class Budget(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(budget.grade(95), 'A')
        self.assertEqual(budget.grade(90), 'A')
        self.assertEqual(budget.grade(85), 'B')

    def test_truncate_words(self):
        self.assertEqual(budget.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(budget.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(budget.truncate_words('', 3), '')
