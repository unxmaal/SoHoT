import unittest

from lantern import sensors


class Sensors(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(sensors.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(sensors.rle(''), [])

    def test_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
