import unittest

from depot.weather import grade
from depot import weather


class Weather(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(grade(95), 'A')
        self.assertEqual(grade(90), 'A')
        self.assertEqual(grade(85), 'B')

    def test_paginate(self):
        self.assertEqual(weather.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(weather.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
