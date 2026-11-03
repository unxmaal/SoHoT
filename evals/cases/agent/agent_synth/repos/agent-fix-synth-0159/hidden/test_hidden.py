import unittest

from tally import stock
from tally import sensors
from tally import kitchen
from tally import billing
from tally import digest


class Hidden(unittest.TestCase):
    def test_stock_snake_case(self):
        self.assertEqual(stock.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(stock.snake_case('plain'), 'plain')
        self.assertEqual(stock.snake_case('A'), 'a')
        self.assertEqual(stock.snake_case('ShipToCity'), 'ship_to_city')

    def test_stock_is_leap(self):
        self.assertEqual(stock.is_leap(2024), True)
        self.assertEqual(stock.is_leap(1900), False)
        self.assertEqual(stock.is_leap(2000), True)
        self.assertEqual(stock.is_leap(2023), False)
        self.assertEqual(stock.is_leap(2400), True)
        self.assertEqual(stock.is_leap(2100), False)

    def test_stock_clamp(self):
        self.assertEqual(stock.clamp(5, 0, 10), 5)
        self.assertEqual(stock.clamp(-3, 0, 10), 0)
        self.assertEqual(stock.clamp(15, 0, 10), 10)
        self.assertEqual(stock.clamp(10, 0, 10), 10)
        self.assertEqual(stock.clamp(0, 0, 10), 0)
        self.assertEqual(stock.clamp(7, 7, 7), 7)
        self.assertEqual(stock.clamp(-20, -30, -10), -20)

    def test_sensors_running_total(self):
        self.assertEqual(sensors.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(sensors.running_total([]), [])
        self.assertEqual(sensors.running_total([5]), [5])
        self.assertEqual(sensors.running_total([2, -2, 2]), [2, 0, 2])

    def test_sensors_median(self):
        self.assertEqual(sensors.median([3, 1, 2]), 2)
        self.assertEqual(sensors.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(sensors.median([5]), 5)
        self.assertEqual(sensors.median([1, 2]), 1.5)
        self.assertEqual(sensors.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            sensors.median([])

    def test_sensors_word_count(self):
        self.assertEqual(sensors.word_count('a b'), 2)
        self.assertEqual(sensors.word_count('  tea  and   milk '), 3)
        self.assertEqual(sensors.word_count(''), 0)
        self.assertEqual(sensors.word_count('one'), 1)

    def test_kitchen_merge_ranges(self):
        self.assertEqual(kitchen.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(kitchen.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(kitchen.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(kitchen.merge_ranges([]), [])
        self.assertEqual(kitchen.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_kitchen_chunk(self):
        self.assertEqual(kitchen.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(kitchen.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(kitchen.chunk([], 3), [])
        self.assertEqual(kitchen.chunk(['a'], 1), [['a']])
        self.assertEqual(kitchen.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            kitchen.chunk([1, 2], 0)

    def test_billing_grade(self):
        self.assertEqual(billing.grade(95), 'A')
        self.assertEqual(billing.grade(90), 'A')
        self.assertEqual(billing.grade(85), 'B')
        self.assertEqual(billing.grade(80), 'B')
        self.assertEqual(billing.grade(61), 'D')
        self.assertEqual(billing.grade(59), 'F')
        self.assertEqual(billing.grade(0), 'F')

    def test_billing_rle(self):
        self.assertEqual(billing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(billing.rle(''), [])
        self.assertEqual(billing.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(billing.rle('zz'), [('z', 2)])

    def test_digest_anchor_view(self):
        self.assertEqual(digest.anchor_view('OrderTotal'), {'anchor_view': 'order_total'})
        self.assertEqual(digest.anchor_view('plain'), {'anchor_view': 'plain'})
        self.assertEqual(digest.anchor_view('A'), {'anchor_view': 'a'})
        self.assertEqual(digest.anchor_view('ShipToCity'), {'anchor_view': 'ship_to_city'})

    def test_digest_sail_row(self):
        self.assertEqual(digest.sail_row(2024), {'sail_row': True})
        self.assertEqual(digest.sail_row(1900), {'sail_row': False})
        self.assertEqual(digest.sail_row(2000), {'sail_row': True})
        self.assertEqual(digest.sail_row(2023), {'sail_row': False})
        self.assertEqual(digest.sail_row(2400), {'sail_row': True})
        self.assertEqual(digest.sail_row(2100), {'sail_row': False})

    def test_digest_deck_summary(self):
        self.assertEqual(digest.deck_summary(5, 0, 10), {'deck_summary': 5})
        self.assertEqual(digest.deck_summary(-3, 0, 10), {'deck_summary': 0})
        self.assertEqual(digest.deck_summary(15, 0, 10), {'deck_summary': 10})
        self.assertEqual(digest.deck_summary(10, 0, 10), {'deck_summary': 10})
        self.assertEqual(digest.deck_summary(0, 0, 10), {'deck_summary': 0})
        self.assertEqual(digest.deck_summary(7, 7, 7), {'deck_summary': 7})
        self.assertEqual(digest.deck_summary(-20, -30, -10), {'deck_summary': -20})

    def test_digest_tide_row(self):
        self.assertEqual(digest.tide_row([1, 2, 3]), {'tide_row': [1, 3, 6]})
        self.assertEqual(digest.tide_row([]), {'tide_row': []})
        self.assertEqual(digest.tide_row([5]), {'tide_row': [5]})
        self.assertEqual(digest.tide_row([2, -2, 2]), {'tide_row': [2, 0, 2]})
