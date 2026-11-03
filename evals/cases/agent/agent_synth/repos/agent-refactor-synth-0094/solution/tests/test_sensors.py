import unittest

from compass.sensors import mark_of


class Sensors(unittest.TestCase):
    def test_mark_of(self):
        self.assertEqual(mark_of(95), 'A')
        self.assertEqual(mark_of(90), 'A')
        self.assertEqual(mark_of(85), 'B')
