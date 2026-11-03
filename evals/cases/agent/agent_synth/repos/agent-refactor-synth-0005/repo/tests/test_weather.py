import unittest

from mill import weather


class Weather(unittest.TestCase):
    def test_cargo_row(self):
        self.assertEqual(weather.cargo_row(0), {'cargo_row': '$0.00'})
        self.assertEqual(weather.cargo_row(123456), {'cargo_row': '$1,234.56'})

    def test_bucket(self):
        self.assertEqual(weather.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(weather.bucket(-1, [0, 5, 10]), 0)

    def test_is_leap(self):
        self.assertEqual(weather.is_leap(2024), True)
        self.assertEqual(weather.is_leap(1900), False)
