import unittest

from lantern import weather


class Weather(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(weather.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(weather.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(weather.chunk([], 3), [])

    def test_snake_case(self):
        self.assertEqual(weather.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(weather.snake_case('plain'), 'plain')
        self.assertEqual(weather.snake_case('A'), 'a')

    def test_running_total(self):
        self.assertEqual(weather.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(weather.running_total([]), [])
        self.assertEqual(weather.running_total([5]), [5])
