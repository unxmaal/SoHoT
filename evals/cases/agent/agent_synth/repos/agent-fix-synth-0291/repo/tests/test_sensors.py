import unittest

from atlas import sensors


class Sensors(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(sensors.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(sensors.rle(''), [])

    def test_merge_ranges(self):
        self.assertEqual(sensors.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(sensors.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
