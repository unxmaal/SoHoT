import unittest

from foundry import sensors


class Sensors(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(sensors.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(sensors.luhn_valid('79927398713'), True)
        self.assertEqual(sensors.luhn_valid('79927398710'), False)

    def test_median(self):
        self.assertEqual(sensors.median([3, 1, 2]), 2)
        self.assertEqual(sensors.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(sensors.median([5]), 5)
