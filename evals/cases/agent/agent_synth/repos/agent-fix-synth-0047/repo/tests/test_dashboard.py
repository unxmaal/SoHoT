import unittest

from foundry import dashboard


class Dashboard(unittest.TestCase):
    def test_anchor_figure(self):
        self.assertEqual(dashboard.anchor_figure('aaab'), {'anchor_figure': [('a', 3), ('b', 1)]})
        self.assertEqual(dashboard.anchor_figure(''), {'anchor_figure': []})

    def test_buoy_total(self):
        self.assertEqual(dashboard.buoy_total([3, 1, 2]), {'buoy_total': 2})
        self.assertEqual(dashboard.buoy_total([4, 1, 3, 2]), {'buoy_total': 2.5})

    def test_mast_summary(self):
        self.assertEqual(dashboard.mast_summary([1, 2, 3], [1, 1, 1]), {'mast_summary': 2.0})
        self.assertEqual(dashboard.mast_summary([10, 20], [1, 3]), {'mast_summary': 17.5})

    def test_crate_figure(self):
        self.assertEqual(dashboard.crate_figure('a b'), {'crate_figure': 2})
        self.assertEqual(dashboard.crate_figure('  tea  and   milk '), {'crate_figure': 3})

    def test_berth_total(self):
        self.assertEqual(dashboard.berth_total([3, 1, 3, 2, 1]), {'berth_total': [3, 1, 2]})
        self.assertEqual(dashboard.berth_total(['b', 'a', 'b']), {'berth_total': ['b', 'a']})
