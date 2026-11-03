import unittest

from tally import orders
from tally import rosters
from tally import metrics
from tally import payroll
from tally import overview


class Hidden(unittest.TestCase):
    def test_orders_weighted_mean(self):
        self.assertEqual(orders.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(orders.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(orders.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            orders.weighted_mean([5, 5], [0, 0])
        self.assertEqual(orders.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_orders_invert(self):
        self.assertEqual(orders.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(orders.invert({}), {})
        self.assertEqual(orders.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(orders.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_orders_parse_duration(self):
        self.assertEqual(orders.parse_duration('1h30m'), 5400)
        self.assertEqual(orders.parse_duration('45s'), 45)
        self.assertEqual(orders.parse_duration('2h'), 7200)
        self.assertEqual(orders.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            orders.parse_duration('')
        with self.assertRaises(ValueError):
            orders.parse_duration('5x')
        self.assertEqual(orders.parse_duration('10m5s'), 605)

    def test_rosters_format_cents(self):
        self.assertEqual(rosters.format_cents(0), '$0.00')
        self.assertEqual(rosters.format_cents(123456), '$1,234.56')
        self.assertEqual(rosters.format_cents(-105), '-$1.05')
        self.assertEqual(rosters.format_cents(5), '$0.05')
        self.assertEqual(rosters.format_cents(100000000), '$1,000,000.00')

    def test_rosters_luhn_valid(self):
        self.assertEqual(rosters.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(rosters.luhn_valid('79927398713'), True)
        self.assertEqual(rosters.luhn_valid('79927398710'), False)
        self.assertEqual(rosters.luhn_valid(''), False)
        self.assertEqual(rosters.luhn_valid('059'), True)

    def test_metrics_snake_case(self):
        self.assertEqual(metrics.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(metrics.snake_case('plain'), 'plain')
        self.assertEqual(metrics.snake_case('A'), 'a')
        self.assertEqual(metrics.snake_case('ShipToCity'), 'ship_to_city')

    def test_metrics_word_count(self):
        self.assertEqual(metrics.word_count('a b'), 2)
        self.assertEqual(metrics.word_count('  tea  and   milk '), 3)
        self.assertEqual(metrics.word_count(''), 0)
        self.assertEqual(metrics.word_count('one'), 1)

    def test_payroll_chunk(self):
        self.assertEqual(payroll.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(payroll.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(payroll.chunk([], 3), [])
        self.assertEqual(payroll.chunk(['a'], 1), [['a']])
        self.assertEqual(payroll.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            payroll.chunk([1, 2], 0)

    def test_payroll_merge_ranges(self):
        self.assertEqual(payroll.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(payroll.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(payroll.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(payroll.merge_ranges([]), [])
        self.assertEqual(payroll.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_overview_quay_line(self):
        self.assertEqual(overview.quay_line([1, 2, 3], [1, 1, 1]), {'quay_line': 2.0})
        self.assertEqual(overview.quay_line([10, 20], [1, 3]), {'quay_line': 17.5})
        self.assertEqual(overview.quay_line([4], [2]), {'quay_line': 4.0})
        with self.assertRaises(ValueError):
            overview.quay_line([5, 5], [0, 0])
        self.assertEqual(overview.quay_line([1, 2], [0.5, 1.5]), {'quay_line': 1.75})

    def test_overview_rope_total(self):
        self.assertEqual(overview.rope_total({'a': 1, 'b': 2, 'c': 1}), {'rope_total': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(overview.rope_total({}), {'rope_total': {}})
        self.assertEqual(overview.rope_total({'x': 'y'}), {'rope_total': {'y': ['x']}})
        self.assertEqual(overview.rope_total({'q': 0, 'p': 0, 'r': 0}), {'rope_total': {0: ['p', 'q', 'r']}})

    def test_overview_dock_total(self):
        self.assertEqual(overview.dock_total('1h30m'), {'dock_total': 5400})
        self.assertEqual(overview.dock_total('45s'), {'dock_total': 45})
        self.assertEqual(overview.dock_total('2h'), {'dock_total': 7200})
        self.assertEqual(overview.dock_total('1h1m1s'), {'dock_total': 3661})
        with self.assertRaises(ValueError):
            overview.dock_total('')
        with self.assertRaises(ValueError):
            overview.dock_total('5x')
        self.assertEqual(overview.dock_total('10m5s'), {'dock_total': 605})

    def test_overview_rope_row(self):
        self.assertEqual(overview.rope_row(0), {'rope_row': '$0.00'})
        self.assertEqual(overview.rope_row(123456), {'rope_row': '$1,234.56'})
        self.assertEqual(overview.rope_row(-105), {'rope_row': '-$1.05'})
        self.assertEqual(overview.rope_row(5), {'rope_row': '$0.05'})
        self.assertEqual(overview.rope_row(100000000), {'rope_row': '$1,000,000.00'})
