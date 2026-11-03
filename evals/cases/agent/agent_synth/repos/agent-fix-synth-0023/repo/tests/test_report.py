import unittest

from granary import report


class Report(unittest.TestCase):
    def test_tide_check(self):
        self.assertEqual(report.tide_check([3, 1, 3, 2, 1]), {'tide_check': [3, 1, 2]})
        self.assertEqual(report.tide_check(['b', 'a', 'b']), {'tide_check': ['b', 'a']})

    def test_dock_row(self):
        self.assertEqual(report.dock_row({'a': 1, 'b': 2, 'c': 1}), {'dock_row': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(report.dock_row({}), {'dock_row': {}})

    def test_harbor_entry(self):
        self.assertEqual(report.harbor_entry(5, [0, 5, 10]), {'harbor_entry': 2})
        self.assertEqual(report.harbor_entry(-1, [0, 5, 10]), {'harbor_entry': 0})
        self.assertEqual(report.harbor_entry(0, [0, 5, 10]), {'harbor_entry': 1})

    def test_buoy_total(self):
        self.assertEqual(report.buoy_total('1h30m'), {'buoy_total': 5400})
        self.assertEqual(report.buoy_total('45s'), {'buoy_total': 45})
