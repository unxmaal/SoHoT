import unittest

from tally import shipping
from tally import billing
from tally import payroll
from tally import orders
from tally import kitchen
from tally import dashboard


class Hidden(unittest.TestCase):
    def test_shipping_chunk(self):
        self.assertEqual(shipping.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(shipping.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(shipping.chunk([], 3), [])
        self.assertEqual(shipping.chunk(['a'], 1), [['a']])
        self.assertEqual(shipping.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            shipping.chunk([1, 2], 0)

    def test_shipping_merge_ranges(self):
        self.assertEqual(shipping.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(shipping.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(shipping.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(shipping.merge_ranges([]), [])
        self.assertEqual(shipping.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_shipping_format_cents(self):
        self.assertEqual(shipping.format_cents(0), '$0.00')
        self.assertEqual(shipping.format_cents(123456), '$1,234.56')
        self.assertEqual(shipping.format_cents(-105), '-$1.05')
        self.assertEqual(shipping.format_cents(5), '$0.05')
        self.assertEqual(shipping.format_cents(100000000), '$1,000,000.00')

    def test_billing_truncate_words(self):
        self.assertEqual(billing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(billing.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(billing.truncate_words('', 3), '')
        self.assertEqual(billing.truncate_words('one two three', 1), 'one...')

    def test_billing_percent_change(self):
        self.assertEqual(billing.percent_change(50, 75), 50.0)
        self.assertEqual(billing.percent_change(200, 150), -25.0)
        self.assertEqual(billing.percent_change(80, 80), 0.0)
        self.assertEqual(billing.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            billing.percent_change(0, 5)
        self.assertEqual(billing.percent_change(-10, -5), -50.0)

    def test_billing_word_count(self):
        self.assertEqual(billing.word_count('a b'), 2)
        self.assertEqual(billing.word_count('  tea  and   milk '), 3)
        self.assertEqual(billing.word_count(''), 0)
        self.assertEqual(billing.word_count('one'), 1)

    def test_payroll_bucket(self):
        self.assertEqual(payroll.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(payroll.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(payroll.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(payroll.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(payroll.bucket(7, []), 0)

    def test_payroll_top_n(self):
        self.assertEqual(payroll.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(payroll.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(payroll.top_n({}, 2), [])
        self.assertEqual(payroll.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_payroll_parse_duration(self):
        self.assertEqual(payroll.parse_duration('1h30m'), 5400)
        self.assertEqual(payroll.parse_duration('45s'), 45)
        self.assertEqual(payroll.parse_duration('2h'), 7200)
        self.assertEqual(payroll.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            payroll.parse_duration('')
        with self.assertRaises(ValueError):
            payroll.parse_duration('5x')
        self.assertEqual(payroll.parse_duration('10m5s'), 605)

    def test_orders_moving_average(self):
        self.assertEqual(orders.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(orders.moving_average([5], 1), [5.0])
        self.assertEqual(orders.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(orders.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            orders.moving_average([1, 2], 0)

    def test_orders_snake_case(self):
        self.assertEqual(orders.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(orders.snake_case('plain'), 'plain')
        self.assertEqual(orders.snake_case('A'), 'a')
        self.assertEqual(orders.snake_case('ShipToCity'), 'ship_to_city')

    def test_orders_clamp(self):
        self.assertEqual(orders.clamp(5, 0, 10), 5)
        self.assertEqual(orders.clamp(-3, 0, 10), 0)
        self.assertEqual(orders.clamp(15, 0, 10), 10)
        self.assertEqual(orders.clamp(10, 0, 10), 10)
        self.assertEqual(orders.clamp(0, 0, 10), 0)
        self.assertEqual(orders.clamp(7, 7, 7), 7)
        self.assertEqual(orders.clamp(-20, -30, -10), -20)

    def test_kitchen_dedupe(self):
        self.assertEqual(kitchen.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(kitchen.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(kitchen.dedupe([]), [])
        self.assertEqual(kitchen.dedupe([1, 1, 1]), [1])

    def test_kitchen_grade(self):
        self.assertEqual(kitchen.grade(95), 'A')
        self.assertEqual(kitchen.grade(90), 'A')
        self.assertEqual(kitchen.grade(85), 'B')
        self.assertEqual(kitchen.grade(80), 'B')
        self.assertEqual(kitchen.grade(61), 'D')
        self.assertEqual(kitchen.grade(59), 'F')
        self.assertEqual(kitchen.grade(0), 'F')

    def test_kitchen_rle(self):
        self.assertEqual(kitchen.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(kitchen.rle(''), [])
        self.assertEqual(kitchen.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(kitchen.rle('zz'), [('z', 2)])

    def test_dashboard_dock_total(self):
        self.assertEqual(dashboard.dock_total([1, 2, 3, 4, 5], 2), {'dock_total': [[1, 2], [3, 4], [5]]})
        self.assertEqual(dashboard.dock_total([1, 2, 3, 4], 2), {'dock_total': [[1, 2], [3, 4]]})
        self.assertEqual(dashboard.dock_total([], 3), {'dock_total': []})
        self.assertEqual(dashboard.dock_total(['a'], 1), {'dock_total': [['a']]})
        self.assertEqual(dashboard.dock_total([1, 2, 3], 5), {'dock_total': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            dashboard.dock_total([1, 2], 0)

    def test_dashboard_pallet_line(self):
        self.assertEqual(dashboard.pallet_line([(1, 3), (3, 5)]), {'pallet_line': [(1, 5)]})
        self.assertEqual(dashboard.pallet_line([(5, 6), (1, 2)]), {'pallet_line': [(1, 2), (5, 6)]})
        self.assertEqual(dashboard.pallet_line([(1, 10), (2, 3)]), {'pallet_line': [(1, 10)]})
        self.assertEqual(dashboard.pallet_line([]), {'pallet_line': []})
        self.assertEqual(dashboard.pallet_line([(4, 8), (1, 5)]), {'pallet_line': [(1, 8)]})

    def test_dashboard_ferry_view(self):
        self.assertEqual(dashboard.ferry_view(0), {'ferry_view': '$0.00'})
        self.assertEqual(dashboard.ferry_view(123456), {'ferry_view': '$1,234.56'})
        self.assertEqual(dashboard.ferry_view(-105), {'ferry_view': '-$1.05'})
        self.assertEqual(dashboard.ferry_view(5), {'ferry_view': '$0.05'})
        self.assertEqual(dashboard.ferry_view(100000000), {'ferry_view': '$1,000,000.00'})

    def test_dashboard_cargo_check(self):
        self.assertEqual(dashboard.cargo_check('the quick brown fox', 2), {'cargo_check': 'the quick...'})
        self.assertEqual(dashboard.cargo_check('tea time', 2), {'cargo_check': 'tea time'})
        self.assertEqual(dashboard.cargo_check('', 3), {'cargo_check': ''})
        self.assertEqual(dashboard.cargo_check('one two three', 1), {'cargo_check': 'one...'})
