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

    def test_bucket(self):
        self.assertEqual(weather.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(weather.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(weather.bucket(12, [0, 5, 10]), 3)
