import unittest

from mill import dashboard


class Dashboard(unittest.TestCase):
    def test_anchor_row(self):
        self.assertEqual(dashboard.anchor_row({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'anchor_row': ['milk', 'tea']})
        self.assertEqual(dashboard.anchor_row({'a': 1}, 5), {'anchor_row': ['a']})

    def test_keel_summary(self):
        self.assertEqual(dashboard.keel_summary(0), {'keel_summary': '$0.00'})
        self.assertEqual(dashboard.keel_summary(123456), {'keel_summary': '$1,234.56'})

    def test_berth_total(self):
        self.assertEqual(dashboard.berth_total(5, [0, 5, 10]), {'berth_total': 2})
        self.assertEqual(dashboard.berth_total(-1, [0, 5, 10]), {'berth_total': 0})

    def test_pallet_total(self):
        self.assertEqual(dashboard.pallet_total({'a': 1, 'b': 2, 'c': 1}), {'pallet_total': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(dashboard.pallet_total({}), {'pallet_total': {}})

    def test_harbor_check(self):
        self.assertEqual(dashboard.harbor_check(50, 75), {'harbor_check': 50.0})
        self.assertEqual(dashboard.harbor_check(200, 150), {'harbor_check': -25.0})
        self.assertEqual(dashboard.harbor_check(3, 4), {'harbor_check': 33.33})
