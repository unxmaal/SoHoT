import unittest

from harbor import weather


class Weather(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(weather.percent_change(50, 75), 50.0)
        self.assertEqual(weather.percent_change(200, 150), -25.0)

    def test_is_leap(self):
        self.assertEqual(weather.is_leap(2024), True)
        self.assertEqual(weather.is_leap(1900), False)
