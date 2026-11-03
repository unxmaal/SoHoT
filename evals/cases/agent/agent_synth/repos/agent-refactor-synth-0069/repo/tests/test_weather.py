import unittest

from quarry import weather


class Weather(unittest.TestCase):
    def test_ferry_figure(self):
        self.assertEqual(weather.ferry_figure('4539 1488 0343 6467'), {'ferry_figure': True})
        self.assertEqual(weather.ferry_figure('79927398713'), {'ferry_figure': True})

    def test_chunk(self):
        self.assertEqual(weather.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(weather.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_moving_average(self):
        self.assertEqual(weather.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(weather.moving_average([5], 1), [5.0])
