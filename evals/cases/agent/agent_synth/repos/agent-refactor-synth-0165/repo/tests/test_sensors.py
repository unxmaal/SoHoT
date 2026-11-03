import unittest

from kiln import sensors


class Sensors(unittest.TestCase):
    def test_anchor_line(self):
        self.assertEqual(sensors.anchor_line([3, 1, 3, 2, 1]), {'anchor_line': [3, 1, 2]})
        self.assertEqual(sensors.anchor_line(['b', 'a', 'b']), {'anchor_line': ['b', 'a']})

    def test_bucket(self):
        self.assertEqual(sensors.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(sensors.bucket(-1, [0, 5, 10]), 0)
