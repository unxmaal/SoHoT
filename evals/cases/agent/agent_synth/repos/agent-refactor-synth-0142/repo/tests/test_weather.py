import unittest

from kiln import weather


class Weather(unittest.TestCase):
    def test_cargo_entry(self):
        self.assertEqual(weather.cargo_entry('the quick brown fox', 2), {'cargo_entry': 'the quick...'})
        self.assertEqual(weather.cargo_entry('tea time', 2), {'cargo_entry': 'tea time'})

    def test_is_leap(self):
        self.assertEqual(weather.is_leap(2024), True)
        self.assertEqual(weather.is_leap(1900), False)

    def test_median(self):
        self.assertEqual(weather.median([3, 1, 2]), 2)
        self.assertEqual(weather.median([4, 1, 3, 2]), 2.5)
