import unittest

from foundry import budget
from foundry import billing
from foundry import timesheet
from foundry import fleet
from foundry import dashboard


class Hidden(unittest.TestCase):
    def test_budget_rle(self):
        self.assertEqual(budget.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(budget.rle(''), [])
        self.assertEqual(budget.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(budget.rle('zz'), [('z', 2)])

    def test_budget_median(self):
        self.assertEqual(budget.median([3, 1, 2]), 2)
        self.assertEqual(budget.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(budget.median([5]), 5)
        self.assertEqual(budget.median([1, 2]), 1.5)
        self.assertEqual(budget.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            budget.median([])

    def test_billing_weighted_mean(self):
        self.assertEqual(billing.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(billing.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(billing.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            billing.weighted_mean([5, 5], [0, 0])
        self.assertEqual(billing.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_billing_word_count(self):
        self.assertEqual(billing.word_count('a b'), 2)
        self.assertEqual(billing.word_count('  tea  and   milk '), 3)
        self.assertEqual(billing.word_count(''), 0)
        self.assertEqual(billing.word_count('one'), 1)

    def test_billing_clamp(self):
        self.assertEqual(billing.clamp(5, 0, 10), 5)
        self.assertEqual(billing.clamp(-3, 0, 10), 0)
        self.assertEqual(billing.clamp(15, 0, 10), 10)
        self.assertEqual(billing.clamp(10, 0, 10), 10)
        self.assertEqual(billing.clamp(0, 0, 10), 0)
        self.assertEqual(billing.clamp(7, 7, 7), 7)
        self.assertEqual(billing.clamp(-20, -30, -10), -20)

    def test_timesheet_format_cents(self):
        self.assertEqual(timesheet.format_cents(0), '$0.00')
        self.assertEqual(timesheet.format_cents(123456), '$1,234.56')
        self.assertEqual(timesheet.format_cents(-105), '-$1.05')
        self.assertEqual(timesheet.format_cents(5), '$0.05')
        self.assertEqual(timesheet.format_cents(100000000), '$1,000,000.00')

    def test_timesheet_dedupe(self):
        self.assertEqual(timesheet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(timesheet.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(timesheet.dedupe([]), [])
        self.assertEqual(timesheet.dedupe([1, 1, 1]), [1])

    def test_timesheet_running_total(self):
        self.assertEqual(timesheet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(timesheet.running_total([]), [])
        self.assertEqual(timesheet.running_total([5]), [5])
        self.assertEqual(timesheet.running_total([2, -2, 2]), [2, 0, 2])

    def test_fleet_truncate_words(self):
        self.assertEqual(fleet.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(fleet.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(fleet.truncate_words('', 3), '')
        self.assertEqual(fleet.truncate_words('one two three', 1), 'one...')

    def test_fleet_is_leap(self):
        self.assertEqual(fleet.is_leap(2024), True)
        self.assertEqual(fleet.is_leap(1900), False)
        self.assertEqual(fleet.is_leap(2000), True)
        self.assertEqual(fleet.is_leap(2023), False)
        self.assertEqual(fleet.is_leap(2400), True)
        self.assertEqual(fleet.is_leap(2100), False)

    def test_dashboard_anchor_figure(self):
        self.assertEqual(dashboard.anchor_figure('aaab'), {'anchor_figure': [('a', 3), ('b', 1)]})
        self.assertEqual(dashboard.anchor_figure(''), {'anchor_figure': []})
        self.assertEqual(dashboard.anchor_figure('abc'), {'anchor_figure': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(dashboard.anchor_figure('zz'), {'anchor_figure': [('z', 2)]})

    def test_dashboard_buoy_total(self):
        self.assertEqual(dashboard.buoy_total([3, 1, 2]), {'buoy_total': 2})
        self.assertEqual(dashboard.buoy_total([4, 1, 3, 2]), {'buoy_total': 2.5})
        self.assertEqual(dashboard.buoy_total([5]), {'buoy_total': 5})
        self.assertEqual(dashboard.buoy_total([1, 2]), {'buoy_total': 1.5})
        self.assertEqual(dashboard.buoy_total([10, 2, 38, 23, 38, 23]), {'buoy_total': 23.0})
        with self.assertRaises(ValueError):
            dashboard.buoy_total([])

    def test_dashboard_mast_summary(self):
        self.assertEqual(dashboard.mast_summary([1, 2, 3], [1, 1, 1]), {'mast_summary': 2.0})
        self.assertEqual(dashboard.mast_summary([10, 20], [1, 3]), {'mast_summary': 17.5})
        self.assertEqual(dashboard.mast_summary([4], [2]), {'mast_summary': 4.0})
        with self.assertRaises(ValueError):
            dashboard.mast_summary([5, 5], [0, 0])
        self.assertEqual(dashboard.mast_summary([1, 2], [0.5, 1.5]), {'mast_summary': 1.75})

    def test_dashboard_crate_figure(self):
        self.assertEqual(dashboard.crate_figure('a b'), {'crate_figure': 2})
        self.assertEqual(dashboard.crate_figure('  tea  and   milk '), {'crate_figure': 3})
        self.assertEqual(dashboard.crate_figure(''), {'crate_figure': 0})
        self.assertEqual(dashboard.crate_figure('one'), {'crate_figure': 1})

    def test_dashboard_berth_total(self):
        self.assertEqual(dashboard.berth_total([3, 1, 3, 2, 1]), {'berth_total': [3, 1, 2]})
        self.assertEqual(dashboard.berth_total(['b', 'a', 'b']), {'berth_total': ['b', 'a']})
        self.assertEqual(dashboard.berth_total([]), {'berth_total': []})
        self.assertEqual(dashboard.berth_total([1, 1, 1]), {'berth_total': [1]})
