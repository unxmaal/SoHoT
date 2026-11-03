import unittest

from wharf import survey


class Survey(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(survey.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(survey.rle(''), [])
        self.assertEqual(survey.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])

    def test_is_leap(self):
        self.assertEqual(survey.is_leap(2024), True)
        self.assertEqual(survey.is_leap(1900), False)
        self.assertEqual(survey.is_leap(2000), True)

    def test_truncate_words(self):
        self.assertEqual(survey.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(survey.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(survey.truncate_words('', 3), '')
