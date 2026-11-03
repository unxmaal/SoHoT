import unittest

from compass import weather
from compass import pricing
from compass import tickets
from compass import summary


class Hidden(unittest.TestCase):
    def test_weather_is_leap(self):
        self.assertEqual(weather.is_leap(2024), True)
        self.assertEqual(weather.is_leap(1900), False)
        self.assertEqual(weather.is_leap(2000), True)
        self.assertEqual(weather.is_leap(2023), False)
        self.assertEqual(weather.is_leap(2400), True)
        self.assertEqual(weather.is_leap(2100), False)

    def test_weather_format_cents(self):
        self.assertEqual(weather.format_cents(0), '$0.00')
        self.assertEqual(weather.format_cents(123456), '$1,234.56')
        self.assertEqual(weather.format_cents(-105), '-$1.05')
        self.assertEqual(weather.format_cents(5), '$0.05')
        self.assertEqual(weather.format_cents(100000000), '$1,000,000.00')

    def test_weather_parse_duration(self):
        self.assertEqual(weather.parse_duration('1h30m'), 5400)
        self.assertEqual(weather.parse_duration('45s'), 45)
        self.assertEqual(weather.parse_duration('2h'), 7200)
        self.assertEqual(weather.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            weather.parse_duration('')
        with self.assertRaises(ValueError):
            weather.parse_duration('5x')
        self.assertEqual(weather.parse_duration('10m5s'), 605)

    def test_pricing_top_n(self):
        self.assertEqual(pricing.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(pricing.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(pricing.top_n({}, 2), [])
        self.assertEqual(pricing.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_pricing_paginate(self):
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(pricing.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            pricing.paginate([1, 2], 0, 2)

    def test_pricing_moving_average(self):
        self.assertEqual(pricing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(pricing.moving_average([5], 1), [5.0])
        self.assertEqual(pricing.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(pricing.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            pricing.moving_average([1, 2], 0)

    def test_tickets_dedupe(self):
        self.assertEqual(tickets.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(tickets.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(tickets.dedupe([]), [])
        self.assertEqual(tickets.dedupe([1, 1, 1]), [1])

    def test_tickets_truncate_words(self):
        self.assertEqual(tickets.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(tickets.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(tickets.truncate_words('', 3), '')
        self.assertEqual(tickets.truncate_words('one two three', 1), 'one...')

    def test_tickets_snake_case(self):
        self.assertEqual(tickets.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(tickets.snake_case('plain'), 'plain')
        self.assertEqual(tickets.snake_case('A'), 'a')
        self.assertEqual(tickets.snake_case('ShipToCity'), 'ship_to_city')

    def test_summary_deck_entry(self):
        self.assertEqual(summary.deck_entry(2024), {'deck_entry': True})
        self.assertEqual(summary.deck_entry(1900), {'deck_entry': False})
        self.assertEqual(summary.deck_entry(2000), {'deck_entry': True})
        self.assertEqual(summary.deck_entry(2023), {'deck_entry': False})
        self.assertEqual(summary.deck_entry(2400), {'deck_entry': True})
        self.assertEqual(summary.deck_entry(2100), {'deck_entry': False})

    def test_summary_ferry_check(self):
        self.assertEqual(summary.ferry_check(0), {'ferry_check': '$0.00'})
        self.assertEqual(summary.ferry_check(123456), {'ferry_check': '$1,234.56'})
        self.assertEqual(summary.ferry_check(-105), {'ferry_check': '-$1.05'})
        self.assertEqual(summary.ferry_check(5), {'ferry_check': '$0.05'})
        self.assertEqual(summary.ferry_check(100000000), {'ferry_check': '$1,000,000.00'})

    def test_summary_buoy_line(self):
        self.assertEqual(summary.buoy_line('1h30m'), {'buoy_line': 5400})
        self.assertEqual(summary.buoy_line('45s'), {'buoy_line': 45})
        self.assertEqual(summary.buoy_line('2h'), {'buoy_line': 7200})
        self.assertEqual(summary.buoy_line('1h1m1s'), {'buoy_line': 3661})
        with self.assertRaises(ValueError):
            summary.buoy_line('')
        with self.assertRaises(ValueError):
            summary.buoy_line('5x')
        self.assertEqual(summary.buoy_line('10m5s'), {'buoy_line': 605})

    def test_summary_buoy_figure(self):
        self.assertEqual(summary.buoy_figure({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'buoy_figure': ['milk', 'tea']})
        self.assertEqual(summary.buoy_figure({'a': 1}, 5), {'buoy_figure': ['a']})
        self.assertEqual(summary.buoy_figure({}, 2), {'buoy_figure': []})
        self.assertEqual(summary.buoy_figure({'x': 2, 'y': 5, 'z': 2}, 2), {'buoy_figure': ['y', 'x']})

    def test_summary_dock_summary(self):
        self.assertEqual(summary.dock_summary([3, 1, 3, 2, 1]), {'dock_summary': [3, 1, 2]})
        self.assertEqual(summary.dock_summary(['b', 'a', 'b']), {'dock_summary': ['b', 'a']})
        self.assertEqual(summary.dock_summary([]), {'dock_summary': []})
        self.assertEqual(summary.dock_summary([1, 1, 1]), {'dock_summary': [1]})
