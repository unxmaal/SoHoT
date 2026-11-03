import unittest

from depot import weather


class Weather(unittest.TestCase):
    def test_quay_figure(self):
        self.assertEqual(weather.quay_figure(95), {'quay_figure': 'A'})
        self.assertEqual(weather.quay_figure(90), {'quay_figure': 'A'})

    def test_invert(self):
        self.assertEqual(weather.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(weather.invert({}), {})

    def test_running_total(self):
        self.assertEqual(weather.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(weather.running_total([]), [])
