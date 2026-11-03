import unittest

from wharf import rosters
from wharf import catalog
from wharf import shipping
from wharf import summary


class Hidden(unittest.TestCase):
    def test_rosters_word_count(self):
        self.assertEqual(rosters.word_count('a b'), 2)
        self.assertEqual(rosters.word_count('  tea  and   milk '), 3)
        self.assertEqual(rosters.word_count(''), 0)
        self.assertEqual(rosters.word_count('one'), 1)

    def test_rosters_is_leap(self):
        self.assertEqual(rosters.is_leap(2024), True)
        self.assertEqual(rosters.is_leap(1900), False)
        self.assertEqual(rosters.is_leap(2000), True)
        self.assertEqual(rosters.is_leap(2023), False)
        self.assertEqual(rosters.is_leap(2400), True)
        self.assertEqual(rosters.is_leap(2100), False)

    def test_catalog_dedupe(self):
        self.assertEqual(catalog.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(catalog.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(catalog.dedupe([]), [])
        self.assertEqual(catalog.dedupe([1, 1, 1]), [1])

    def test_catalog_parse_duration(self):
        self.assertEqual(catalog.parse_duration('1h30m'), 5400)
        self.assertEqual(catalog.parse_duration('45s'), 45)
        self.assertEqual(catalog.parse_duration('2h'), 7200)
        self.assertEqual(catalog.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            catalog.parse_duration('')
        with self.assertRaises(ValueError):
            catalog.parse_duration('5x')
        self.assertEqual(catalog.parse_duration('10m5s'), 605)

    def test_shipping_invert(self):
        self.assertEqual(shipping.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(shipping.invert({}), {})
        self.assertEqual(shipping.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(shipping.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_shipping_luhn_valid(self):
        self.assertEqual(shipping.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(shipping.luhn_valid('79927398713'), True)
        self.assertEqual(shipping.luhn_valid('79927398710'), False)
        self.assertEqual(shipping.luhn_valid(''), False)
        self.assertEqual(shipping.luhn_valid('059'), True)

    def test_shipping_snake_case(self):
        self.assertEqual(shipping.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(shipping.snake_case('plain'), 'plain')
        self.assertEqual(shipping.snake_case('A'), 'a')
        self.assertEqual(shipping.snake_case('ShipToCity'), 'ship_to_city')

    def test_summary_hull_view(self):
        self.assertEqual(summary.hull_view('a b'), {'hull_view': 2})
        self.assertEqual(summary.hull_view('  tea  and   milk '), {'hull_view': 3})
        self.assertEqual(summary.hull_view(''), {'hull_view': 0})
        self.assertEqual(summary.hull_view('one'), {'hull_view': 1})

    def test_summary_anchor_row(self):
        self.assertEqual(summary.anchor_row(2024), {'anchor_row': True})
        self.assertEqual(summary.anchor_row(1900), {'anchor_row': False})
        self.assertEqual(summary.anchor_row(2000), {'anchor_row': True})
        self.assertEqual(summary.anchor_row(2023), {'anchor_row': False})
        self.assertEqual(summary.anchor_row(2400), {'anchor_row': True})
        self.assertEqual(summary.anchor_row(2100), {'anchor_row': False})

    def test_summary_ferry_check(self):
        self.assertEqual(summary.ferry_check([3, 1, 3, 2, 1]), {'ferry_check': [3, 1, 2]})
        self.assertEqual(summary.ferry_check(['b', 'a', 'b']), {'ferry_check': ['b', 'a']})
        self.assertEqual(summary.ferry_check([]), {'ferry_check': []})
        self.assertEqual(summary.ferry_check([1, 1, 1]), {'ferry_check': [1]})

    def test_summary_barge_figure(self):
        self.assertEqual(summary.barge_figure('1h30m'), {'barge_figure': 5400})
        self.assertEqual(summary.barge_figure('45s'), {'barge_figure': 45})
        self.assertEqual(summary.barge_figure('2h'), {'barge_figure': 7200})
        self.assertEqual(summary.barge_figure('1h1m1s'), {'barge_figure': 3661})
        with self.assertRaises(ValueError):
            summary.barge_figure('')
        with self.assertRaises(ValueError):
            summary.barge_figure('5x')
        self.assertEqual(summary.barge_figure('10m5s'), {'barge_figure': 605})
