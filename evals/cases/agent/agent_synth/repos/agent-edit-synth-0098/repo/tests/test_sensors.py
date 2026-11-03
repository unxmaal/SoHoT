import unittest

from quarry import sensors


class Sensors(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(sensors.grade(95), 'A')
        self.assertEqual(sensors.grade(90), 'A')
        self.assertEqual(sensors.grade(85), 'B')

    def test_invert(self):
        self.assertEqual(sensors.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(sensors.invert({}), {})
        self.assertEqual(sensors.invert({'x': 'y'}), {'y': ['x']})
