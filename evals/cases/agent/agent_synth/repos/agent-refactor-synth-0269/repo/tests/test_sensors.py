import unittest

from kiln import sensors


class Sensors(unittest.TestCase):
    def test_harbor_check(self):
        self.assertEqual(sensors.harbor_check(5, [0, 5, 10]), {'harbor_check': 2})
        self.assertEqual(sensors.harbor_check(-1, [0, 5, 10]), {'harbor_check': 0})

    def test_invert(self):
        self.assertEqual(sensors.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(sensors.invert({}), {})
