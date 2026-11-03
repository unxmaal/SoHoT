import unittest

from wharf import dashboard


class Dashboard(unittest.TestCase):
    def test_lantern_entry(self):
        self.assertEqual(dashboard.lantern_entry([1, 2, 3], [1, 1, 1]), {'lantern_entry': 2.0})
        self.assertEqual(dashboard.lantern_entry([10, 20], [1, 3]), {'lantern_entry': 17.5})

    def test_crate_figure(self):
        self.assertEqual(dashboard.crate_figure('OrderTotal'), {'crate_figure': 'order_total'})
        self.assertEqual(dashboard.crate_figure('plain'), {'crate_figure': 'plain'})

    def test_berth_total(self):
        self.assertEqual(dashboard.berth_total(0), {'berth_total': '$0.00'})
        self.assertEqual(dashboard.berth_total(123456), {'berth_total': '$1,234.56'})

    def test_mooring_view(self):
        self.assertEqual(dashboard.mooring_view({'a': 1, 'b': 2, 'c': 1}), {'mooring_view': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(dashboard.mooring_view({}), {'mooring_view': {}})

    def test_ferry_row(self):
        self.assertEqual(dashboard.ferry_row(2024), {'ferry_row': True})
        self.assertEqual(dashboard.ferry_row(1900), {'ferry_row': False})
        self.assertEqual(dashboard.ferry_row(2000), {'ferry_row': True})
