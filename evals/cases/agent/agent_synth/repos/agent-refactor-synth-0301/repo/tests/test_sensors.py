import unittest

from foundry import sensors


class Sensors(unittest.TestCase):
    def test_tide_summary(self):
        self.assertEqual(sensors.tide_summary('4539 1488 0343 6467'), {'tide_summary': True})
        self.assertEqual(sensors.tide_summary('79927398713'), {'tide_summary': True})

    def test_rle(self):
        self.assertEqual(sensors.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(sensors.rle(''), [])

    def test_chunk(self):
        self.assertEqual(sensors.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(sensors.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
