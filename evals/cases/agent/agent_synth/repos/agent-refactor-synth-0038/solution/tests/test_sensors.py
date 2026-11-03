import unittest

from granary.sensors import words_in
from granary import sensors


class Sensors(unittest.TestCase):
    def test_words_in(self):
        self.assertEqual(words_in('a b'), 2)
        self.assertEqual(words_in('  tea  and   milk '), 3)
        self.assertEqual(words_in(''), 0)

    def test_clamp(self):
        self.assertEqual(sensors.clamp(5, 0, 10), 5)
        self.assertEqual(sensors.clamp(-3, 0, 10), 0)
