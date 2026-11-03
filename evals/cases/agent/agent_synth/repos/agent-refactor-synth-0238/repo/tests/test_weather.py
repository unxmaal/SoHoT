import unittest

from orchard import weather


class Weather(unittest.TestCase):
    def test_mooring_summary(self):
        self.assertEqual(weather.mooring_summary([3, 1, 3, 2, 1]), {'mooring_summary': [3, 1, 2]})
        self.assertEqual(weather.mooring_summary(['b', 'a', 'b']), {'mooring_summary': ['b', 'a']})

    def test_bucket(self):
        self.assertEqual(weather.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(weather.bucket(-1, [0, 5, 10]), 0)
