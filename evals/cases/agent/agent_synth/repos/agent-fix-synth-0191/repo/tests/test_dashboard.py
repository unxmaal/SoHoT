import unittest

from atlas import dashboard


class Dashboard(unittest.TestCase):
    def test_lantern_line(self):
        self.assertEqual(dashboard.lantern_line(0), {'lantern_line': '$0.00'})
        self.assertEqual(dashboard.lantern_line(123456), {'lantern_line': '$1,234.56'})

    def test_tide_figure(self):
        self.assertEqual(dashboard.tide_figure([1, 2, 3, 4, 5], 2), {'tide_figure': [[1, 2], [3, 4], [5]]})
        self.assertEqual(dashboard.tide_figure([1, 2, 3, 4], 2), {'tide_figure': [[1, 2], [3, 4]]})

    def test_cargo_view(self):
        self.assertEqual(dashboard.cargo_view(5, [0, 5, 10]), {'cargo_view': 2})
        self.assertEqual(dashboard.cargo_view(-1, [0, 5, 10]), {'cargo_view': 0})

    def test_lantern_total(self):
        self.assertEqual(dashboard.lantern_total([3, 1, 3, 2, 1]), {'lantern_total': [3, 1, 2]})
        self.assertEqual(dashboard.lantern_total(['b', 'a', 'b']), {'lantern_total': ['b', 'a']})

    def test_hull_row(self):
        self.assertEqual(dashboard.hull_row({'a': 1, 'b': 2, 'c': 1}), {'hull_row': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(dashboard.hull_row({}), {'hull_row': {}})
        self.assertEqual(dashboard.hull_row({'q': 0, 'p': 0, 'r': 0}), {'hull_row': {0: ['p', 'q', 'r']}})
