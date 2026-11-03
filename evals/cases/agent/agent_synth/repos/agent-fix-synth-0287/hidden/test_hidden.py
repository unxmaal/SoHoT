import unittest

from harbor import orders
from harbor import shipping
from harbor import weather
from harbor import routes
from harbor import overview


class Hidden(unittest.TestCase):
    def test_orders_moving_average(self):
        self.assertEqual(orders.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(orders.moving_average([5], 1), [5.0])
        self.assertEqual(orders.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(orders.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            orders.moving_average([1, 2], 0)

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

    def test_shipping_merge_ranges(self):
        self.assertEqual(shipping.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(shipping.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(shipping.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(shipping.merge_ranges([]), [])
        self.assertEqual(shipping.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_shipping_chunk(self):
        self.assertEqual(shipping.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(shipping.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(shipping.chunk([], 3), [])
        self.assertEqual(shipping.chunk(['a'], 1), [['a']])
        self.assertEqual(shipping.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            shipping.chunk([1, 2], 0)

    def test_weather_percent_change(self):
        self.assertEqual(weather.percent_change(50, 75), 50.0)
        self.assertEqual(weather.percent_change(200, 150), -25.0)
        self.assertEqual(weather.percent_change(80, 80), 0.0)
        self.assertEqual(weather.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            weather.percent_change(0, 5)
        self.assertEqual(weather.percent_change(-10, -5), -50.0)

    def test_weather_median(self):
        self.assertEqual(weather.median([3, 1, 2]), 2)
        self.assertEqual(weather.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(weather.median([5]), 5)
        self.assertEqual(weather.median([1, 2]), 1.5)
        self.assertEqual(weather.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            weather.median([])

    def test_weather_format_cents(self):
        self.assertEqual(weather.format_cents(0), '$0.00')
        self.assertEqual(weather.format_cents(123456), '$1,234.56')
        self.assertEqual(weather.format_cents(-105), '-$1.05')
        self.assertEqual(weather.format_cents(5), '$0.05')
        self.assertEqual(weather.format_cents(100000000), '$1,000,000.00')

    def test_routes_word_count(self):
        self.assertEqual(routes.word_count('a b'), 2)
        self.assertEqual(routes.word_count('  tea  and   milk '), 3)
        self.assertEqual(routes.word_count(''), 0)
        self.assertEqual(routes.word_count('one'), 1)

    def test_routes_dedupe(self):
        self.assertEqual(routes.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(routes.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(routes.dedupe([]), [])
        self.assertEqual(routes.dedupe([1, 1, 1]), [1])

    def test_routes_luhn_valid(self):
        self.assertEqual(routes.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(routes.luhn_valid('79927398713'), True)
        self.assertEqual(routes.luhn_valid('79927398710'), False)
        self.assertEqual(routes.luhn_valid(''), False)
        self.assertEqual(routes.luhn_valid('059'), True)

    def test_overview_ferry_row(self):
        self.assertEqual(overview.ferry_row([1, 2, 3, 4], 2), {'ferry_row': [1.5, 2.5, 3.5]})
        self.assertEqual(overview.ferry_row([5], 1), {'ferry_row': [5.0]})
        self.assertEqual(overview.ferry_row([1, 2, 3], 3), {'ferry_row': [2.0]})
        self.assertEqual(overview.ferry_row([2, 4, 6, 8, 10], 3), {'ferry_row': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            overview.ferry_row([1, 2], 0)

    def test_overview_quay_line(self):
        self.assertEqual(overview.quay_line('1h30m'), {'quay_line': 5400})
        self.assertEqual(overview.quay_line('45s'), {'quay_line': 45})
        self.assertEqual(overview.quay_line('2h'), {'quay_line': 7200})
        self.assertEqual(overview.quay_line('1h1m1s'), {'quay_line': 3661})
        with self.assertRaises(ValueError):
            overview.quay_line('')
        with self.assertRaises(ValueError):
            overview.quay_line('5x')
        self.assertEqual(overview.quay_line('10m5s'), {'quay_line': 605})

    def test_overview_mooring_check(self):
        self.assertEqual(overview.mooring_check([(1, 3), (3, 5)]), {'mooring_check': [(1, 5)]})
        self.assertEqual(overview.mooring_check([(5, 6), (1, 2)]), {'mooring_check': [(1, 2), (5, 6)]})
        self.assertEqual(overview.mooring_check([(1, 10), (2, 3)]), {'mooring_check': [(1, 10)]})
        self.assertEqual(overview.mooring_check([]), {'mooring_check': []})
        self.assertEqual(overview.mooring_check([(4, 8), (1, 5)]), {'mooring_check': [(1, 8)]})

    def test_overview_harbor_entry(self):
        self.assertEqual(overview.harbor_entry([1, 2, 3, 4, 5], 2), {'harbor_entry': [[1, 2], [3, 4], [5]]})
        self.assertEqual(overview.harbor_entry([1, 2, 3, 4], 2), {'harbor_entry': [[1, 2], [3, 4]]})
        self.assertEqual(overview.harbor_entry([], 3), {'harbor_entry': []})
        self.assertEqual(overview.harbor_entry(['a'], 1), {'harbor_entry': [['a']]})
        self.assertEqual(overview.harbor_entry([1, 2, 3], 5), {'harbor_entry': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            overview.harbor_entry([1, 2], 0)

    def test_overview_rope_entry(self):
        self.assertEqual(overview.rope_entry(50, 75), {'rope_entry': 50.0})
        self.assertEqual(overview.rope_entry(200, 150), {'rope_entry': -25.0})
        self.assertEqual(overview.rope_entry(80, 80), {'rope_entry': 0.0})
        self.assertEqual(overview.rope_entry(3, 4), {'rope_entry': 33.33})
        with self.assertRaises(ValueError):
            overview.rope_entry(0, 5)
        self.assertEqual(overview.rope_entry(-10, -5), {'rope_entry': -50.0})
