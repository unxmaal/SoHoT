import unittest

from foundry import sensors


class Sensors(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(sensors.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(sensors.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(sensors.chunk([], 3), [])

    def test_clamp(self):
        self.assertEqual(sensors.clamp(5, 0, 10), 5)
        self.assertEqual(sensors.clamp(-3, 0, 10), 0)
        self.assertEqual(sensors.clamp(15, 0, 10), 10)

    def test_luhn_valid(self):
        self.assertEqual(sensors.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(sensors.luhn_valid('79927398713'), True)
        self.assertEqual(sensors.luhn_valid('79927398710'), False)
