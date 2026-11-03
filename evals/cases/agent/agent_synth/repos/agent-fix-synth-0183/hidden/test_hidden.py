import unittest

from granary import archive
from granary import budget
from granary import rosters
from granary import orders
from granary import pricing
from granary import dashboard


class Hidden(unittest.TestCase):
    def test_archive_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(archive.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            archive.weighted_mean([5, 5], [0, 0])
        self.assertEqual(archive.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_archive_luhn_valid(self):
        self.assertEqual(archive.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(archive.luhn_valid('79927398713'), True)
        self.assertEqual(archive.luhn_valid('79927398710'), False)
        self.assertEqual(archive.luhn_valid(''), False)
        self.assertEqual(archive.luhn_valid('059'), True)

    def test_archive_paginate(self):
        self.assertEqual(archive.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(archive.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(archive.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(archive.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            archive.paginate([1, 2], 0, 2)

    def test_budget_snake_case(self):
        self.assertEqual(budget.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(budget.snake_case('plain'), 'plain')
        self.assertEqual(budget.snake_case('A'), 'a')
        self.assertEqual(budget.snake_case('ShipToCity'), 'ship_to_city')

    def test_budget_bucket(self):
        self.assertEqual(budget.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(budget.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(budget.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(budget.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(budget.bucket(7, []), 0)

    def test_budget_moving_average(self):
        self.assertEqual(budget.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(budget.moving_average([5], 1), [5.0])
        self.assertEqual(budget.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(budget.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            budget.moving_average([1, 2], 0)

    def test_rosters_merge_ranges(self):
        self.assertEqual(rosters.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(rosters.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(rosters.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(rosters.merge_ranges([]), [])
        self.assertEqual(rosters.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_rosters_is_leap(self):
        self.assertEqual(rosters.is_leap(2024), True)
        self.assertEqual(rosters.is_leap(1900), False)
        self.assertEqual(rosters.is_leap(2000), True)
        self.assertEqual(rosters.is_leap(2023), False)
        self.assertEqual(rosters.is_leap(2400), True)
        self.assertEqual(rosters.is_leap(2100), False)

    def test_rosters_percent_change(self):
        self.assertEqual(rosters.percent_change(50, 75), 50.0)
        self.assertEqual(rosters.percent_change(200, 150), -25.0)
        self.assertEqual(rosters.percent_change(80, 80), 0.0)
        self.assertEqual(rosters.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            rosters.percent_change(0, 5)
        self.assertEqual(rosters.percent_change(-10, -5), -50.0)

    def test_orders_grade(self):
        self.assertEqual(orders.grade(95), 'A')
        self.assertEqual(orders.grade(90), 'A')
        self.assertEqual(orders.grade(85), 'B')
        self.assertEqual(orders.grade(80), 'B')
        self.assertEqual(orders.grade(61), 'D')
        self.assertEqual(orders.grade(59), 'F')
        self.assertEqual(orders.grade(0), 'F')

    def test_orders_rle(self):
        self.assertEqual(orders.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(orders.rle(''), [])
        self.assertEqual(orders.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(orders.rle('zz'), [('z', 2)])

    def test_pricing_dedupe(self):
        self.assertEqual(pricing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(pricing.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(pricing.dedupe([]), [])
        self.assertEqual(pricing.dedupe([1, 1, 1]), [1])

    def test_pricing_median(self):
        self.assertEqual(pricing.median([3, 1, 2]), 2)
        self.assertEqual(pricing.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(pricing.median([5]), 5)
        self.assertEqual(pricing.median([1, 2]), 1.5)
        self.assertEqual(pricing.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            pricing.median([])

    def test_pricing_invert(self):
        self.assertEqual(pricing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(pricing.invert({}), {})
        self.assertEqual(pricing.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(pricing.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_dashboard_keel_check(self):
        self.assertEqual(dashboard.keel_check([1, 2, 3], [1, 1, 1]), {'keel_check': 2.0})
        self.assertEqual(dashboard.keel_check([10, 20], [1, 3]), {'keel_check': 17.5})
        self.assertEqual(dashboard.keel_check([4], [2]), {'keel_check': 4.0})
        with self.assertRaises(ValueError):
            dashboard.keel_check([5, 5], [0, 0])
        self.assertEqual(dashboard.keel_check([1, 2], [0.5, 1.5]), {'keel_check': 1.75})

    def test_dashboard_tide_summary(self):
        self.assertEqual(dashboard.tide_summary('4539 1488 0343 6467'), {'tide_summary': True})
        self.assertEqual(dashboard.tide_summary('79927398713'), {'tide_summary': True})
        self.assertEqual(dashboard.tide_summary('79927398710'), {'tide_summary': False})
        self.assertEqual(dashboard.tide_summary(''), {'tide_summary': False})
        self.assertEqual(dashboard.tide_summary('059'), {'tide_summary': True})

    def test_dashboard_anchor_row(self):
        self.assertEqual(dashboard.anchor_row([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), {'anchor_row': [1, 2, 3]})
        self.assertEqual(dashboard.anchor_row([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), {'anchor_row': [10]})
        self.assertEqual(dashboard.anchor_row([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), {'anchor_row': []})
        self.assertEqual(dashboard.anchor_row([], 1, 5), {'anchor_row': []})
        with self.assertRaises(ValueError):
            dashboard.anchor_row([1, 2], 0, 2)

    def test_dashboard_lantern_total(self):
        self.assertEqual(dashboard.lantern_total('OrderTotal'), {'lantern_total': 'order_total'})
        self.assertEqual(dashboard.lantern_total('plain'), {'lantern_total': 'plain'})
        self.assertEqual(dashboard.lantern_total('A'), {'lantern_total': 'a'})
        self.assertEqual(dashboard.lantern_total('ShipToCity'), {'lantern_total': 'ship_to_city'})

    def test_dashboard_quay_total(self):
        self.assertEqual(dashboard.quay_total(5, [0, 5, 10]), {'quay_total': 2})
        self.assertEqual(dashboard.quay_total(-1, [0, 5, 10]), {'quay_total': 0})
        self.assertEqual(dashboard.quay_total(12, [0, 5, 10]), {'quay_total': 3})
        self.assertEqual(dashboard.quay_total(0, [0, 5, 10]), {'quay_total': 1})
        self.assertEqual(dashboard.quay_total(7, []), {'quay_total': 0})
