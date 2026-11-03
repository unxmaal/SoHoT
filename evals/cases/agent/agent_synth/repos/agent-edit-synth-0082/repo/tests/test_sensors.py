import unittest

from compass import sensors


class Sensors(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(sensors.is_leap(2024), True)
        self.assertEqual(sensors.is_leap(1900), False)
        self.assertEqual(sensors.is_leap(2000), True)

    def test_weighted_mean(self):
        self.assertEqual(sensors.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(sensors.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(sensors.weighted_mean([4], [2]), 4.0)

    def test_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)
