import unittest

from kiln import sensors


class Sensors(unittest.TestCase):
    def test_invert(self):
        self.assertEqual(sensors.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(sensors.invert({}), {})

    def test_grade(self):
        self.assertEqual(sensors.grade(95), 'A')
        self.assertEqual(sensors.grade(90), 'A')
        self.assertEqual(sensors.grade(80), 'B')

    def test_paginate(self):
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
