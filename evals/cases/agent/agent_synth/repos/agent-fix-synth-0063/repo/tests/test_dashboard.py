import unittest

from tally import dashboard


class Dashboard(unittest.TestCase):
    def test_dock_total(self):
        self.assertEqual(dashboard.dock_total([1, 2, 3, 4, 5], 2), {'dock_total': [[1, 2], [3, 4], [5]]})
        self.assertEqual(dashboard.dock_total([1, 2, 3, 4], 2), {'dock_total': [[1, 2], [3, 4]]})
        self.assertEqual(dashboard.dock_total(['a'], 1), {'dock_total': [['a']]})

    def test_pallet_line(self):
        self.assertEqual(dashboard.pallet_line([(1, 3), (3, 5)]), {'pallet_line': [(1, 5)]})
        self.assertEqual(dashboard.pallet_line([(5, 6), (1, 2)]), {'pallet_line': [(1, 2), (5, 6)]})

    def test_ferry_view(self):
        self.assertEqual(dashboard.ferry_view(0), {'ferry_view': '$0.00'})
        self.assertEqual(dashboard.ferry_view(123456), {'ferry_view': '$1,234.56'})

    def test_cargo_check(self):
        self.assertEqual(dashboard.cargo_check('the quick brown fox', 2), {'cargo_check': 'the quick...'})
        self.assertEqual(dashboard.cargo_check('tea time', 2), {'cargo_check': 'tea time'})
