import unittest

from atlas import sensors


class Sensors(unittest.TestCase):
    def test_pallet_total(self):
        self.assertEqual(sensors.pallet_total(95), {'pallet_total': 'A'})
        self.assertEqual(sensors.pallet_total(90), {'pallet_total': 'A'})

    def test_weighted_mean(self):
        self.assertEqual(sensors.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(sensors.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_clamp(self):
        self.assertEqual(sensors.clamp(5, 0, 10), 5)
        self.assertEqual(sensors.clamp(-3, 0, 10), 0)
