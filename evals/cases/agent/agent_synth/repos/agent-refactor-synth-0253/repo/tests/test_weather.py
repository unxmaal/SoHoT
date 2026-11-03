import unittest

from atlas import weather


class Weather(unittest.TestCase):
    def test_crate_total(self):
        self.assertEqual(weather.crate_total({'a': 1, 'b': 2, 'c': 1}), {'crate_total': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(weather.crate_total({}), {'crate_total': {}})

    def test_is_leap(self):
        self.assertEqual(weather.is_leap(2024), True)
        self.assertEqual(weather.is_leap(1900), False)
