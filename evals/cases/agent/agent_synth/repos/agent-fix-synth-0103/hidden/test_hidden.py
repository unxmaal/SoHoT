import unittest

from mill import stock
from mill import tickets
from mill import rosters
from mill import budget
from mill import sensors
from mill import dashboard


class Hidden(unittest.TestCase):
    def test_stock_top_n(self):
        self.assertEqual(stock.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(stock.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(stock.top_n({}, 2), [])
        self.assertEqual(stock.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_stock_format_cents(self):
        self.assertEqual(stock.format_cents(0), '$0.00')
        self.assertEqual(stock.format_cents(123456), '$1,234.56')
        self.assertEqual(stock.format_cents(-105), '-$1.05')
        self.assertEqual(stock.format_cents(5), '$0.05')
        self.assertEqual(stock.format_cents(100000000), '$1,000,000.00')

    def test_stock_bucket(self):
        self.assertEqual(stock.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(stock.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(stock.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(stock.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(stock.bucket(7, []), 0)

    def test_tickets_invert(self):
        self.assertEqual(tickets.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(tickets.invert({}), {})
        self.assertEqual(tickets.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(tickets.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_tickets_merge_ranges(self):
        self.assertEqual(tickets.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(tickets.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(tickets.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(tickets.merge_ranges([]), [])
        self.assertEqual(tickets.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_tickets_percent_change(self):
        self.assertEqual(tickets.percent_change(50, 75), 50.0)
        self.assertEqual(tickets.percent_change(200, 150), -25.0)
        self.assertEqual(tickets.percent_change(80, 80), 0.0)
        self.assertEqual(tickets.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            tickets.percent_change(0, 5)
        self.assertEqual(tickets.percent_change(-10, -5), -50.0)

    def test_rosters_dedupe(self):
        self.assertEqual(rosters.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(rosters.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(rosters.dedupe([]), [])
        self.assertEqual(rosters.dedupe([1, 1, 1]), [1])

    def test_rosters_clamp(self):
        self.assertEqual(rosters.clamp(5, 0, 10), 5)
        self.assertEqual(rosters.clamp(-3, 0, 10), 0)
        self.assertEqual(rosters.clamp(15, 0, 10), 10)
        self.assertEqual(rosters.clamp(10, 0, 10), 10)
        self.assertEqual(rosters.clamp(0, 0, 10), 0)
        self.assertEqual(rosters.clamp(7, 7, 7), 7)
        self.assertEqual(rosters.clamp(-20, -30, -10), -20)

    def test_rosters_running_total(self):
        self.assertEqual(rosters.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(rosters.running_total([]), [])
        self.assertEqual(rosters.running_total([5]), [5])
        self.assertEqual(rosters.running_total([2, -2, 2]), [2, 0, 2])

    def test_budget_median(self):
        self.assertEqual(budget.median([3, 1, 2]), 2)
        self.assertEqual(budget.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(budget.median([5]), 5)
        self.assertEqual(budget.median([1, 2]), 1.5)
        self.assertEqual(budget.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            budget.median([])

    def test_budget_snake_case(self):
        self.assertEqual(budget.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(budget.snake_case('plain'), 'plain')
        self.assertEqual(budget.snake_case('A'), 'a')
        self.assertEqual(budget.snake_case('ShipToCity'), 'ship_to_city')

    def test_sensors_luhn_valid(self):
        self.assertEqual(sensors.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(sensors.luhn_valid('79927398713'), True)
        self.assertEqual(sensors.luhn_valid('79927398710'), False)
        self.assertEqual(sensors.luhn_valid(''), False)
        self.assertEqual(sensors.luhn_valid('059'), True)

    def test_sensors_is_leap(self):
        self.assertEqual(sensors.is_leap(2024), True)
        self.assertEqual(sensors.is_leap(1900), False)
        self.assertEqual(sensors.is_leap(2000), True)
        self.assertEqual(sensors.is_leap(2023), False)
        self.assertEqual(sensors.is_leap(2400), True)
        self.assertEqual(sensors.is_leap(2100), False)

    def test_dashboard_anchor_row(self):
        self.assertEqual(dashboard.anchor_row({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'anchor_row': ['milk', 'tea']})
        self.assertEqual(dashboard.anchor_row({'a': 1}, 5), {'anchor_row': ['a']})
        self.assertEqual(dashboard.anchor_row({}, 2), {'anchor_row': []})
        self.assertEqual(dashboard.anchor_row({'x': 2, 'y': 5, 'z': 2}, 2), {'anchor_row': ['y', 'x']})

    def test_dashboard_keel_summary(self):
        self.assertEqual(dashboard.keel_summary(0), {'keel_summary': '$0.00'})
        self.assertEqual(dashboard.keel_summary(123456), {'keel_summary': '$1,234.56'})
        self.assertEqual(dashboard.keel_summary(-105), {'keel_summary': '-$1.05'})
        self.assertEqual(dashboard.keel_summary(5), {'keel_summary': '$0.05'})
        self.assertEqual(dashboard.keel_summary(100000000), {'keel_summary': '$1,000,000.00'})

    def test_dashboard_berth_total(self):
        self.assertEqual(dashboard.berth_total(5, [0, 5, 10]), {'berth_total': 2})
        self.assertEqual(dashboard.berth_total(-1, [0, 5, 10]), {'berth_total': 0})
        self.assertEqual(dashboard.berth_total(12, [0, 5, 10]), {'berth_total': 3})
        self.assertEqual(dashboard.berth_total(0, [0, 5, 10]), {'berth_total': 1})
        self.assertEqual(dashboard.berth_total(7, []), {'berth_total': 0})

    def test_dashboard_pallet_total(self):
        self.assertEqual(dashboard.pallet_total({'a': 1, 'b': 2, 'c': 1}), {'pallet_total': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(dashboard.pallet_total({}), {'pallet_total': {}})
        self.assertEqual(dashboard.pallet_total({'x': 'y'}), {'pallet_total': {'y': ['x']}})
        self.assertEqual(dashboard.pallet_total({'q': 0, 'p': 0, 'r': 0}), {'pallet_total': {0: ['p', 'q', 'r']}})

    def test_dashboard_harbor_check(self):
        self.assertEqual(dashboard.harbor_check(50, 75), {'harbor_check': 50.0})
        self.assertEqual(dashboard.harbor_check(200, 150), {'harbor_check': -25.0})
        self.assertEqual(dashboard.harbor_check(80, 80), {'harbor_check': 0.0})
        self.assertEqual(dashboard.harbor_check(3, 4), {'harbor_check': 33.33})
        with self.assertRaises(ValueError):
            dashboard.harbor_check(0, 5)
        self.assertEqual(dashboard.harbor_check(-10, -5), {'harbor_check': -50.0})
