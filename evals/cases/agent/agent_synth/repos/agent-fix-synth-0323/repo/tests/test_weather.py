import unittest

from foundry import weather


class Weather(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(weather.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(weather.snake_case('plain'), 'plain')

    def test_invert(self):
        self.assertEqual(weather.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(weather.invert({}), {})

    def test_percent_change(self):
        self.assertEqual(weather.percent_change(50, 75), 50.0)
        self.assertEqual(weather.percent_change(200, 150), -25.0)
