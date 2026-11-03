import unittest

from depot import routes


class Routes(unittest.TestCase):
    def test_tide_figure(self):
        self.assertEqual(routes.tide_figure([1, 2, 3]), {'tide_figure': [1, 3, 6]})
        self.assertEqual(routes.tide_figure([]), {'tide_figure': []})

    def test_percent_change(self):
        self.assertEqual(routes.percent_change(50, 75), 50.0)
        self.assertEqual(routes.percent_change(200, 150), -25.0)

    def test_rle(self):
        self.assertEqual(routes.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(routes.rle(''), [])
