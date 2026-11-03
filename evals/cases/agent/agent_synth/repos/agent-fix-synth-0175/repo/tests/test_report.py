import unittest

from wharf import report


class Report(unittest.TestCase):
    def test_mooring_total(self):
        self.assertEqual(report.mooring_total({'a': 1, 'b': 2, 'c': 1}), {'mooring_total': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(report.mooring_total({}), {'mooring_total': {}})

    def test_harbor_row(self):
        self.assertEqual(report.harbor_row([(1, 3), (3, 5)]), {'harbor_row': [(1, 5)]})
        self.assertEqual(report.harbor_row([(5, 6), (1, 2)]), {'harbor_row': [(1, 2), (5, 6)]})

    def test_berth_view(self):
        self.assertEqual(report.berth_view([1, 2, 3, 4], 2), {'berth_view': [1.5, 2.5, 3.5]})
        self.assertEqual(report.berth_view([5], 1), {'berth_view': [5.0]})

    def test_buoy_view(self):
        self.assertEqual(report.buoy_view('aaab'), {'buoy_view': [('a', 3), ('b', 1)]})
        self.assertEqual(report.buoy_view(''), {'buoy_view': []})

    def test_berth_total(self):
        self.assertEqual(report.berth_total('the quick brown fox', 2), {'berth_total': 'the quick...'})
        self.assertEqual(report.berth_total('tea time', 2), {'berth_total': 'tea time'})
