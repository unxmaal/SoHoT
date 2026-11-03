import unittest

from harbor import weather


class Weather(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(weather.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(weather.moving_average([5], 1), [5.0])
        self.assertEqual(weather.moving_average([1, 2, 3], 3), [2.0])

    def test_percent_change(self):
        self.assertEqual(weather.percent_change(50, 75), 50.0)
        self.assertEqual(weather.percent_change(200, 150), -25.0)

    def test_chunk(self):
        self.assertEqual(weather.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(weather.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
