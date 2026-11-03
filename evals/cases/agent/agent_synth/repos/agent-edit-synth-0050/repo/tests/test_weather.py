import unittest

from depot import weather


class Weather(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(weather.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(weather.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(weather.truncate_words('', 3), '')

    def test_grade(self):
        self.assertEqual(weather.grade(95), 'A')
        self.assertEqual(weather.grade(90), 'A')
        self.assertEqual(weather.grade(85), 'B')

    def test_merge_ranges(self):
        self.assertEqual(weather.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(weather.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(weather.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
