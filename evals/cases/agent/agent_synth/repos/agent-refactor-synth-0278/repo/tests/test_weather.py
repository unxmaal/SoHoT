import unittest

from granary import weather


class Weather(unittest.TestCase):
    def test_harbor_total(self):
        self.assertEqual(weather.harbor_total([(1, 3), (3, 5)]), {'harbor_total': [(1, 5)]})
        self.assertEqual(weather.harbor_total([(5, 6), (1, 2)]), {'harbor_total': [(1, 2), (5, 6)]})

    def test_format_cents(self):
        self.assertEqual(weather.format_cents(0), '$0.00')
        self.assertEqual(weather.format_cents(123456), '$1,234.56')
