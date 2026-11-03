import unittest

from harbor import sensors


class Sensors(unittest.TestCase):
    def test_median(self):
        self.assertEqual(sensors.median([3, 1, 2]), 2)
        self.assertEqual(sensors.median([4, 1, 3, 2]), 2.5)

    def test_parse_duration(self):
        self.assertEqual(sensors.parse_duration('1h30m'), 5400)
        self.assertEqual(sensors.parse_duration('45s'), 45)
        self.assertEqual(sensors.parse_duration('2h'), 7200)
