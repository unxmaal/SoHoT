import unittest

from harbor import weather


class Weather(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(weather.parse_duration('1h30m'), 5400)
        self.assertEqual(weather.parse_duration('45s'), 45)

    def test_truncate_words(self):
        self.assertEqual(weather.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(weather.truncate_words('tea time', 2), 'tea time')

    def test_merge_ranges(self):
        self.assertEqual(weather.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(weather.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
