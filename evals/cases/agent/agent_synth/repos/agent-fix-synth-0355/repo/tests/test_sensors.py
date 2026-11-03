import unittest

from orchard import sensors


class Sensors(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(sensors.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(sensors.truncate_words('tea time', 2), 'tea time')

    def test_word_count(self):
        self.assertEqual(sensors.word_count('a b'), 2)
        self.assertEqual(sensors.word_count('  tea  and   milk '), 3)

    def test_top_n(self):
        self.assertEqual(sensors.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(sensors.top_n({'a': 1}, 5), ['a'])
