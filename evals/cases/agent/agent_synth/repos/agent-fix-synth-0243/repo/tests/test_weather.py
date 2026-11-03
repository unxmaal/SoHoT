import unittest

from mill import weather


class Weather(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(weather.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(weather.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_rle(self):
        self.assertEqual(weather.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(weather.rle(''), [])

    def test_is_leap(self):
        self.assertEqual(weather.is_leap(2024), True)
        self.assertEqual(weather.is_leap(1900), False)
        self.assertEqual(weather.is_leap(2100), False)
