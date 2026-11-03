import unittest

from wharf import weather


class Weather(unittest.TestCase):
    def test_pallet_row(self):
        self.assertEqual(weather.pallet_row(50, 75), {'pallet_row': 50.0})
        self.assertEqual(weather.pallet_row(200, 150), {'pallet_row': -25.0})

    def test_word_count(self):
        self.assertEqual(weather.word_count('a b'), 2)
        self.assertEqual(weather.word_count('  tea  and   milk '), 3)
