import unittest

from lantern import sensors


class Sensors(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)

    def test_bucket(self):
        self.assertEqual(sensors.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(sensors.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(sensors.bucket(12, [0, 5, 10]), 3)
