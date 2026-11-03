import unittest

from foundry import sensors


class Sensors(unittest.TestCase):
    def test_buoy_entry(self):
        self.assertEqual(sensors.buoy_entry(5, 0, 10), {'buoy_entry': 5})
        self.assertEqual(sensors.buoy_entry(-3, 0, 10), {'buoy_entry': 0})

    def test_paginate(self):
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
