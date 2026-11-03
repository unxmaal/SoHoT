import unittest

from tally import sensors


class Sensors(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(sensors.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(sensors.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(sensors.chunk([], 3), [])

    def test_moving_average(self):
        self.assertEqual(sensors.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(sensors.moving_average([5], 1), [5.0])
        self.assertEqual(sensors.moving_average([1, 2, 3], 3), [2.0])

    def test_invert(self):
        self.assertEqual(sensors.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(sensors.invert({}), {})
        self.assertEqual(sensors.invert({'x': 'y'}), {'y': ['x']})
