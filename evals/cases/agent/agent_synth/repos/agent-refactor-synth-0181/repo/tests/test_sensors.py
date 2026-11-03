import unittest

from harbor import sensors


class Sensors(unittest.TestCase):
    def test_mooring_check(self):
        self.assertEqual(sensors.mooring_check(95), {'mooring_check': 'A'})
        self.assertEqual(sensors.mooring_check(90), {'mooring_check': 'A'})

    def test_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)

    def test_clamp(self):
        self.assertEqual(sensors.clamp(5, 0, 10), 5)
        self.assertEqual(sensors.clamp(-3, 0, 10), 0)
