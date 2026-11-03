import unittest

from atlas.weather import shorten


class Weather(unittest.TestCase):
    def test_shorten(self):
        self.assertEqual(shorten('the quick brown fox', 2), 'the quick...')
        self.assertEqual(shorten('tea time', 2), 'tea time')
        self.assertEqual(shorten('', 3), '')
