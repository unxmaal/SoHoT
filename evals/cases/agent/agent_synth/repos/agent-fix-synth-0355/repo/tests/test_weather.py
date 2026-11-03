import unittest

from orchard import weather


class Weather(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(weather.format_cents(0), '$0.00')
        self.assertEqual(weather.format_cents(123456), '$1,234.56')

    def test_bucket(self):
        self.assertEqual(weather.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(weather.bucket(-1, [0, 5, 10]), 0)

    def test_percent_change(self):
        self.assertEqual(weather.percent_change(50, 75), 50.0)
        self.assertEqual(weather.percent_change(200, 150), -25.0)
