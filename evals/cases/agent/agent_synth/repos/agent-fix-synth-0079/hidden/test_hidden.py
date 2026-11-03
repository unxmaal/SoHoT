import unittest

from wharf import stock
from wharf import billing
from wharf import fleet
from wharf import survey
from wharf import budget
from wharf import dashboard


class Hidden(unittest.TestCase):
    def test_stock_weighted_mean(self):
        self.assertEqual(stock.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(stock.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(stock.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            stock.weighted_mean([5, 5], [0, 0])
        self.assertEqual(stock.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_stock_snake_case(self):
        self.assertEqual(stock.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(stock.snake_case('plain'), 'plain')
        self.assertEqual(stock.snake_case('A'), 'a')
        self.assertEqual(stock.snake_case('ShipToCity'), 'ship_to_city')

    def test_billing_format_cents(self):
        self.assertEqual(billing.format_cents(0), '$0.00')
        self.assertEqual(billing.format_cents(123456), '$1,234.56')
        self.assertEqual(billing.format_cents(-105), '-$1.05')
        self.assertEqual(billing.format_cents(5), '$0.05')
        self.assertEqual(billing.format_cents(100000000), '$1,000,000.00')

    def test_billing_invert(self):
        self.assertEqual(billing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(billing.invert({}), {})
        self.assertEqual(billing.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(billing.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_billing_grade(self):
        self.assertEqual(billing.grade(95), 'A')
        self.assertEqual(billing.grade(90), 'A')
        self.assertEqual(billing.grade(85), 'B')
        self.assertEqual(billing.grade(80), 'B')
        self.assertEqual(billing.grade(61), 'D')
        self.assertEqual(billing.grade(59), 'F')
        self.assertEqual(billing.grade(0), 'F')

    def test_fleet_parse_duration(self):
        self.assertEqual(fleet.parse_duration('1h30m'), 5400)
        self.assertEqual(fleet.parse_duration('45s'), 45)
        self.assertEqual(fleet.parse_duration('2h'), 7200)
        self.assertEqual(fleet.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            fleet.parse_duration('')
        with self.assertRaises(ValueError):
            fleet.parse_duration('5x')
        self.assertEqual(fleet.parse_duration('10m5s'), 605)

    def test_fleet_luhn_valid(self):
        self.assertEqual(fleet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(fleet.luhn_valid('79927398713'), True)
        self.assertEqual(fleet.luhn_valid('79927398710'), False)
        self.assertEqual(fleet.luhn_valid(''), False)
        self.assertEqual(fleet.luhn_valid('059'), True)

    def test_fleet_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
        self.assertEqual(fleet.running_total([5]), [5])
        self.assertEqual(fleet.running_total([2, -2, 2]), [2, 0, 2])

    def test_survey_rle(self):
        self.assertEqual(survey.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(survey.rle(''), [])
        self.assertEqual(survey.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(survey.rle('zz'), [('z', 2)])

    def test_survey_is_leap(self):
        self.assertEqual(survey.is_leap(2024), True)
        self.assertEqual(survey.is_leap(1900), False)
        self.assertEqual(survey.is_leap(2000), True)
        self.assertEqual(survey.is_leap(2023), False)
        self.assertEqual(survey.is_leap(2400), True)
        self.assertEqual(survey.is_leap(2100), False)

    def test_survey_merge_ranges(self):
        self.assertEqual(survey.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(survey.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(survey.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(survey.merge_ranges([]), [])
        self.assertEqual(survey.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_budget_median(self):
        self.assertEqual(budget.median([3, 1, 2]), 2)
        self.assertEqual(budget.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(budget.median([5]), 5)
        self.assertEqual(budget.median([1, 2]), 1.5)
        self.assertEqual(budget.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            budget.median([])

    def test_budget_clamp(self):
        self.assertEqual(budget.clamp(5, 0, 10), 5)
        self.assertEqual(budget.clamp(-3, 0, 10), 0)
        self.assertEqual(budget.clamp(15, 0, 10), 10)
        self.assertEqual(budget.clamp(10, 0, 10), 10)
        self.assertEqual(budget.clamp(0, 0, 10), 0)
        self.assertEqual(budget.clamp(7, 7, 7), 7)
        self.assertEqual(budget.clamp(-20, -30, -10), -20)

    def test_budget_chunk(self):
        self.assertEqual(budget.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(budget.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(budget.chunk([], 3), [])
        self.assertEqual(budget.chunk(['a'], 1), [['a']])
        self.assertEqual(budget.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            budget.chunk([1, 2], 0)

    def test_dashboard_lantern_entry(self):
        self.assertEqual(dashboard.lantern_entry([1, 2, 3], [1, 1, 1]), {'lantern_entry': 2.0})
        self.assertEqual(dashboard.lantern_entry([10, 20], [1, 3]), {'lantern_entry': 17.5})
        self.assertEqual(dashboard.lantern_entry([4], [2]), {'lantern_entry': 4.0})
        with self.assertRaises(ValueError):
            dashboard.lantern_entry([5, 5], [0, 0])
        self.assertEqual(dashboard.lantern_entry([1, 2], [0.5, 1.5]), {'lantern_entry': 1.75})

    def test_dashboard_crate_figure(self):
        self.assertEqual(dashboard.crate_figure('OrderTotal'), {'crate_figure': 'order_total'})
        self.assertEqual(dashboard.crate_figure('plain'), {'crate_figure': 'plain'})
        self.assertEqual(dashboard.crate_figure('A'), {'crate_figure': 'a'})
        self.assertEqual(dashboard.crate_figure('ShipToCity'), {'crate_figure': 'ship_to_city'})

    def test_dashboard_berth_total(self):
        self.assertEqual(dashboard.berth_total(0), {'berth_total': '$0.00'})
        self.assertEqual(dashboard.berth_total(123456), {'berth_total': '$1,234.56'})
        self.assertEqual(dashboard.berth_total(-105), {'berth_total': '-$1.05'})
        self.assertEqual(dashboard.berth_total(5), {'berth_total': '$0.05'})
        self.assertEqual(dashboard.berth_total(100000000), {'berth_total': '$1,000,000.00'})

    def test_dashboard_mooring_view(self):
        self.assertEqual(dashboard.mooring_view({'a': 1, 'b': 2, 'c': 1}), {'mooring_view': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(dashboard.mooring_view({}), {'mooring_view': {}})
        self.assertEqual(dashboard.mooring_view({'x': 'y'}), {'mooring_view': {'y': ['x']}})
        self.assertEqual(dashboard.mooring_view({'q': 0, 'p': 0, 'r': 0}), {'mooring_view': {0: ['p', 'q', 'r']}})

    def test_dashboard_ferry_row(self):
        self.assertEqual(dashboard.ferry_row(2024), {'ferry_row': True})
        self.assertEqual(dashboard.ferry_row(1900), {'ferry_row': False})
        self.assertEqual(dashboard.ferry_row(2000), {'ferry_row': True})
        self.assertEqual(dashboard.ferry_row(2023), {'ferry_row': False})
        self.assertEqual(dashboard.ferry_row(2400), {'ferry_row': True})
        self.assertEqual(dashboard.ferry_row(2100), {'ferry_row': False})
