import unittest

from foundry import report


class Report(unittest.TestCase):
    def test_sail_line(self):
        self.assertEqual(report.sail_line(0), {'sail_line': '$0.00'})
        self.assertEqual(report.sail_line(123456), {'sail_line': '$1,234.56'})

    def test_lantern_summary(self):
        self.assertEqual(report.lantern_summary('OrderTotal'), {'lantern_summary': 'order_total'})
        self.assertEqual(report.lantern_summary('plain'), {'lantern_summary': 'plain'})

    def test_anchor_summary(self):
        self.assertEqual(report.anchor_summary('1h30m'), {'anchor_summary': 5400})
        self.assertEqual(report.anchor_summary('45s'), {'anchor_summary': 45})

    def test_tide_total(self):
        self.assertEqual(report.tide_total([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), {'tide_total': [1, 2, 3]})
        self.assertEqual(report.tide_total([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), {'tide_total': [10]})

    def test_cargo_figure(self):
        self.assertEqual(report.cargo_figure('aaab'), {'cargo_figure': [('a', 3), ('b', 1)]})
        self.assertEqual(report.cargo_figure(''), {'cargo_figure': []})
        self.assertEqual(report.cargo_figure('abc'), {'cargo_figure': [('a', 1), ('b', 1), ('c', 1)]})
