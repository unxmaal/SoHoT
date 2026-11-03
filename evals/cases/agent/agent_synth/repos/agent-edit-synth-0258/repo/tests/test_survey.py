import unittest

from quarry import survey


class Survey(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(survey.word_count('a b'), 2)
        self.assertEqual(survey.word_count('  tea  and   milk '), 3)
        self.assertEqual(survey.word_count(''), 0)

    def test_percent_change(self):
        self.assertEqual(survey.percent_change(50, 75), 50.0)
        self.assertEqual(survey.percent_change(200, 150), -25.0)
        self.assertEqual(survey.percent_change(80, 80), 0.0)

    def test_invert(self):
        self.assertEqual(survey.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(survey.invert({}), {})
        self.assertEqual(survey.invert({'x': 'y'}), {'y': ['x']})
