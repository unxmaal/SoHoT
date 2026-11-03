import unittest

from mill import weather


class Weather(unittest.TestCase):
    def test_anchor_line(self):
        self.assertEqual(weather.anchor_line('4539 1488 0343 6467'), {'anchor_line': True})
        self.assertEqual(weather.anchor_line('79927398713'), {'anchor_line': True})

    def test_clamp(self):
        self.assertEqual(weather.clamp(5, 0, 10), 5)
        self.assertEqual(weather.clamp(-3, 0, 10), 0)

    def test_moving_average(self):
        self.assertEqual(weather.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(weather.moving_average([5], 1), [5.0])
