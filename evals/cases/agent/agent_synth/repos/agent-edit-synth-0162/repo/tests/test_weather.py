import unittest

from depot import weather


class Weather(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(weather.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(weather.rle(''), [])
        self.assertEqual(weather.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])

    def test_top_n(self):
        self.assertEqual(weather.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(weather.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(weather.top_n({}, 2), [])
