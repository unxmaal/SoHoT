import unittest

from tally import sensors


class Sensors(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)

    def test_grade(self):
        self.assertEqual(sensors.grade(95), 'A')
        self.assertEqual(sensors.grade(90), 'A')
        self.assertEqual(sensors.grade(80), 'B')

    def test_word_count(self):
        self.assertEqual(sensors.word_count('a b'), 2)
        self.assertEqual(sensors.word_count('  tea  and   milk '), 3)
