import unittest

from meadow import weather


class Weather(unittest.TestCase):
    def test_harbor_total(self):
        self.assertEqual(weather.harbor_total([(1, 3), (3, 5)]), {'harbor_total': [(1, 5)]})
        self.assertEqual(weather.harbor_total([(5, 6), (1, 2)]), {'harbor_total': [(1, 2), (5, 6)]})

    def test_parse_duration(self):
        self.assertEqual(weather.parse_duration('1h30m'), 5400)
        self.assertEqual(weather.parse_duration('45s'), 45)

    def test_invert(self):
        self.assertEqual(weather.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(weather.invert({}), {})
