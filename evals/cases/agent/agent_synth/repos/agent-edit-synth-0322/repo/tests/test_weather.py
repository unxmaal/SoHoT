import unittest

from foundry import weather


class Weather(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(weather.word_count('a b'), 2)
        self.assertEqual(weather.word_count('  tea  and   milk '), 3)
        self.assertEqual(weather.word_count(''), 0)

    def test_dedupe(self):
        self.assertEqual(weather.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(weather.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(weather.dedupe([]), [])
