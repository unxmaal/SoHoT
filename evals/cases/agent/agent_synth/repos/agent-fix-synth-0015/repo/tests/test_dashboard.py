import unittest

from mill import dashboard


class Dashboard(unittest.TestCase):
    def test_sail_figure(self):
        self.assertEqual(dashboard.sail_figure('the quick brown fox', 2), {'sail_figure': 'the quick...'})
        self.assertEqual(dashboard.sail_figure('tea time', 2), {'sail_figure': 'tea time'})

    def test_mooring_line(self):
        self.assertEqual(dashboard.mooring_line(2024), {'mooring_line': True})
        self.assertEqual(dashboard.mooring_line(1900), {'mooring_line': False})

    def test_ferry_check(self):
        self.assertEqual(dashboard.ferry_check(50, 75), {'ferry_check': 50.0})
        self.assertEqual(dashboard.ferry_check(200, 150), {'ferry_check': -25.0})

    def test_quay_summary(self):
        self.assertEqual(dashboard.quay_summary('a b'), {'quay_summary': 2})
        self.assertEqual(dashboard.quay_summary('  tea  and   milk '), {'quay_summary': 3})
        self.assertEqual(dashboard.quay_summary(''), {'quay_summary': 0})
