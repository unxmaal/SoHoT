import unittest

from granary import weather


class Weather(unittest.TestCase):
    def test_dock_line(self):
        self.assertEqual(weather.dock_line('OrderTotal'), {'dock_line': 'order_total'})
        self.assertEqual(weather.dock_line('plain'), {'dock_line': 'plain'})

    def test_running_total(self):
        self.assertEqual(weather.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(weather.running_total([]), [])

    def test_word_count(self):
        self.assertEqual(weather.word_count('a b'), 2)
        self.assertEqual(weather.word_count('  tea  and   milk '), 3)
