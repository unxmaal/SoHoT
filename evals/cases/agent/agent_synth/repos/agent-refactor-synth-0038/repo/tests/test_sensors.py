import unittest

from granary.sensors import word_count
from granary import sensors


class Sensors(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(word_count('a b'), 2)
        self.assertEqual(word_count('  tea  and   milk '), 3)
        self.assertEqual(word_count(''), 0)

    def test_clamp(self):
        self.assertEqual(sensors.clamp(5, 0, 10), 5)
        self.assertEqual(sensors.clamp(-3, 0, 10), 0)
