import unittest

from mill import pricing
from mill import ledger
from mill import orders
from mill import budget
from mill import digest


class Hidden(unittest.TestCase):
    def test_pricing_format_cents(self):
        self.assertEqual(pricing.format_cents(0), '$0.00')
        self.assertEqual(pricing.format_cents(123456), '$1,234.56')
        self.assertEqual(pricing.format_cents(-105), '-$1.05')
        self.assertEqual(pricing.format_cents(5), '$0.05')
        self.assertEqual(pricing.format_cents(100000000), '$1,000,000.00')

    def test_pricing_top_n(self):
        self.assertEqual(pricing.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(pricing.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(pricing.top_n({}, 2), [])
        self.assertEqual(pricing.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_pricing_moving_average(self):
        self.assertEqual(pricing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(pricing.moving_average([5], 1), [5.0])
        self.assertEqual(pricing.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(pricing.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            pricing.moving_average([1, 2], 0)

    def test_ledger_is_leap(self):
        self.assertEqual(ledger.is_leap(2024), True)
        self.assertEqual(ledger.is_leap(1900), False)
        self.assertEqual(ledger.is_leap(2000), True)
        self.assertEqual(ledger.is_leap(2023), False)
        self.assertEqual(ledger.is_leap(2400), True)
        self.assertEqual(ledger.is_leap(2100), False)

    def test_ledger_snake_case(self):
        self.assertEqual(ledger.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(ledger.snake_case('plain'), 'plain')
        self.assertEqual(ledger.snake_case('A'), 'a')
        self.assertEqual(ledger.snake_case('ShipToCity'), 'ship_to_city')

    def test_ledger_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)
        self.assertEqual(ledger.clamp(15, 0, 10), 10)
        self.assertEqual(ledger.clamp(10, 0, 10), 10)
        self.assertEqual(ledger.clamp(0, 0, 10), 0)
        self.assertEqual(ledger.clamp(7, 7, 7), 7)
        self.assertEqual(ledger.clamp(-20, -30, -10), -20)

    def test_orders_rle(self):
        self.assertEqual(orders.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(orders.rle(''), [])
        self.assertEqual(orders.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(orders.rle('zz'), [('z', 2)])

    def test_orders_median(self):
        self.assertEqual(orders.median([3, 1, 2]), 2)
        self.assertEqual(orders.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(orders.median([5]), 5)
        self.assertEqual(orders.median([1, 2]), 1.5)
        self.assertEqual(orders.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            orders.median([])

    def test_budget_chunk(self):
        self.assertEqual(budget.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(budget.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(budget.chunk([], 3), [])
        self.assertEqual(budget.chunk(['a'], 1), [['a']])
        self.assertEqual(budget.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            budget.chunk([1, 2], 0)

    def test_budget_parse_duration(self):
        self.assertEqual(budget.parse_duration('1h30m'), 5400)
        self.assertEqual(budget.parse_duration('45s'), 45)
        self.assertEqual(budget.parse_duration('2h'), 7200)
        self.assertEqual(budget.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            budget.parse_duration('')
        with self.assertRaises(ValueError):
            budget.parse_duration('5x')
        self.assertEqual(budget.parse_duration('10m5s'), 605)

    def test_budget_weighted_mean(self):
        self.assertEqual(budget.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(budget.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(budget.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            budget.weighted_mean([5, 5], [0, 0])
        self.assertEqual(budget.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_digest_anchor_entry(self):
        self.assertEqual(digest.anchor_entry(0), {'anchor_entry': '$0.00'})
        self.assertEqual(digest.anchor_entry(123456), {'anchor_entry': '$1,234.56'})
        self.assertEqual(digest.anchor_entry(-105), {'anchor_entry': '-$1.05'})
        self.assertEqual(digest.anchor_entry(5), {'anchor_entry': '$0.05'})
        self.assertEqual(digest.anchor_entry(100000000), {'anchor_entry': '$1,000,000.00'})

    def test_digest_hull_line(self):
        self.assertEqual(digest.hull_line({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'hull_line': ['milk', 'tea']})
        self.assertEqual(digest.hull_line({'a': 1}, 5), {'hull_line': ['a']})
        self.assertEqual(digest.hull_line({}, 2), {'hull_line': []})
        self.assertEqual(digest.hull_line({'x': 2, 'y': 5, 'z': 2}, 2), {'hull_line': ['y', 'x']})

    def test_digest_cargo_summary(self):
        self.assertEqual(digest.cargo_summary([1, 2, 3, 4], 2), {'cargo_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(digest.cargo_summary([5], 1), {'cargo_summary': [5.0]})
        self.assertEqual(digest.cargo_summary([1, 2, 3], 3), {'cargo_summary': [2.0]})
        self.assertEqual(digest.cargo_summary([2, 4, 6, 8, 10], 3), {'cargo_summary': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            digest.cargo_summary([1, 2], 0)

    def test_digest_lantern_figure(self):
        self.assertEqual(digest.lantern_figure(2024), {'lantern_figure': True})
        self.assertEqual(digest.lantern_figure(1900), {'lantern_figure': False})
        self.assertEqual(digest.lantern_figure(2000), {'lantern_figure': True})
        self.assertEqual(digest.lantern_figure(2023), {'lantern_figure': False})
        self.assertEqual(digest.lantern_figure(2400), {'lantern_figure': True})
        self.assertEqual(digest.lantern_figure(2100), {'lantern_figure': False})

    def test_digest_ferry_view(self):
        self.assertEqual(digest.ferry_view([1, 2, 3], [1, 1, 1]), {'ferry_view': 2.0})
        self.assertEqual(digest.ferry_view([10, 20], [1, 3]), {'ferry_view': 17.5})
        self.assertEqual(digest.ferry_view([4], [2]), {'ferry_view': 4.0})
        with self.assertRaises(ValueError):
            digest.ferry_view([5, 5], [0, 0])
        self.assertEqual(digest.ferry_view([1, 2], [0.5, 1.5]), {'ferry_view': 1.75})
