import unittest

from beacon import weather


class Weather(unittest.TestCase):
    def test_pallet_summary(self):
        self.assertEqual(weather.pallet_summary([3, 1, 3, 2, 1]), {'pallet_summary': [3, 1, 2]})
        self.assertEqual(weather.pallet_summary(['b', 'a', 'b']), {'pallet_summary': ['b', 'a']})

    def test_rle(self):
        self.assertEqual(weather.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(weather.rle(''), [])
