import unittest

from wharf import summary


class Summary(unittest.TestCase):
    def test_hull_view(self):
        self.assertEqual(summary.hull_view('a b'), {'hull_view': 2})
        self.assertEqual(summary.hull_view('  tea  and   milk '), {'hull_view': 3})
        self.assertEqual(summary.hull_view(''), {'hull_view': 0})

    def test_anchor_row(self):
        self.assertEqual(summary.anchor_row(2024), {'anchor_row': True})
        self.assertEqual(summary.anchor_row(1900), {'anchor_row': False})

    def test_ferry_check(self):
        self.assertEqual(summary.ferry_check([3, 1, 3, 2, 1]), {'ferry_check': [3, 1, 2]})
        self.assertEqual(summary.ferry_check(['b', 'a', 'b']), {'ferry_check': ['b', 'a']})

    def test_barge_figure(self):
        self.assertEqual(summary.barge_figure('1h30m'), {'barge_figure': 5400})
        self.assertEqual(summary.barge_figure('45s'), {'barge_figure': 45})
