import unittest

from beacon.sensors import weighted_mean
from beacon import sensors


class Sensors(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertEqual(weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(weighted_mean([4], [2]), 4.0)

    def test_format_cents(self):
        self.assertEqual(sensors.format_cents(0), '$0.00')
        self.assertEqual(sensors.format_cents(123456), '$1,234.56')
