import unittest

from atlas import dashboard


class Dashboard(unittest.TestCase):
    def test_pallet_row(self):
        self.assertEqual(dashboard.pallet_row([3, 1, 2]), {'pallet_row': 2})
        self.assertEqual(dashboard.pallet_row([4, 1, 3, 2]), {'pallet_row': 2.5})

    def test_mooring_figure(self):
        self.assertEqual(dashboard.mooring_figure('1h30m'), {'mooring_figure': 5400})
        self.assertEqual(dashboard.mooring_figure('45s'), {'mooring_figure': 45})

    def test_berth_check(self):
        self.assertEqual(dashboard.berth_check(95), {'berth_check': 'A'})
        self.assertEqual(dashboard.berth_check(90), {'berth_check': 'A'})

    def test_ferry_figure(self):
        self.assertEqual(dashboard.ferry_figure('the quick brown fox', 2), {'ferry_figure': 'the quick...'})
        self.assertEqual(dashboard.ferry_figure('tea time', 2), {'ferry_figure': 'tea time'})

    def test_barge_summary(self):
        self.assertEqual(dashboard.barge_summary([(1, 3), (3, 5)]), {'barge_summary': [(1, 5)]})
        self.assertEqual(dashboard.barge_summary([(5, 6), (1, 2)]), {'barge_summary': [(1, 2), (5, 6)]})
        self.assertEqual(dashboard.barge_summary([(1, 10), (2, 3)]), {'barge_summary': [(1, 10)]})
