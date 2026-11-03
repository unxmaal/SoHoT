import unittest

from mill import report


class Report(unittest.TestCase):
    def test_ferry_entry(self):
        self.assertEqual(report.ferry_entry('OrderTotal'), {'ferry_entry': 'order_total'})
        self.assertEqual(report.ferry_entry('plain'), {'ferry_entry': 'plain'})

    def test_mast_figure(self):
        self.assertEqual(report.mast_figure([(1, 3), (3, 5)]), {'mast_figure': [(1, 5)]})
        self.assertEqual(report.mast_figure([(5, 6), (1, 2)]), {'mast_figure': [(1, 2), (5, 6)]})

    def test_dock_check(self):
        self.assertEqual(report.dock_check([1, 2, 3]), {'dock_check': [1, 3, 6]})
        self.assertEqual(report.dock_check([]), {'dock_check': []})

    def test_quay_line(self):
        self.assertEqual(report.quay_line({'a': 1, 'b': 2, 'c': 1}), {'quay_line': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(report.quay_line({}), {'quay_line': {}})

    def test_crate_check(self):
        self.assertEqual(report.crate_check(5, [0, 5, 10]), {'crate_check': 2})
        self.assertEqual(report.crate_check(-1, [0, 5, 10]), {'crate_check': 0})
        self.assertEqual(report.crate_check(0, [0, 5, 10]), {'crate_check': 1})
