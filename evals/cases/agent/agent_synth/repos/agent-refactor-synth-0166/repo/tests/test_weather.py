import unittest

from atlas.weather import truncate_words


class Weather(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(truncate_words('tea time', 2), 'tea time')
        self.assertEqual(truncate_words('', 3), '')
