import unittest

from depot import rosters
from depot import weather
from depot import tickets
from depot import budget
from depot import stock
from depot import report


class Hidden(unittest.TestCase):
    def test_rosters_merge_ranges(self):
        self.assertEqual(rosters.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(rosters.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(rosters.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(rosters.merge_ranges([]), [])
        self.assertEqual(rosters.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_rosters_snake_case(self):
        self.assertEqual(rosters.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(rosters.snake_case('plain'), 'plain')
        self.assertEqual(rosters.snake_case('A'), 'a')
        self.assertEqual(rosters.snake_case('ShipToCity'), 'ship_to_city')

    def test_weather_median(self):
        self.assertEqual(weather.median([3, 1, 2]), 2)
        self.assertEqual(weather.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(weather.median([5]), 5)
        self.assertEqual(weather.median([1, 2]), 1.5)
        self.assertEqual(weather.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            weather.median([])

    def test_weather_bucket(self):
        self.assertEqual(weather.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(weather.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(weather.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(weather.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(weather.bucket(7, []), 0)

    def test_tickets_top_n(self):
        self.assertEqual(tickets.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(tickets.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(tickets.top_n({}, 2), [])
        self.assertEqual(tickets.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_tickets_dedupe(self):
        self.assertEqual(tickets.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(tickets.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(tickets.dedupe([]), [])
        self.assertEqual(tickets.dedupe([1, 1, 1]), [1])

    def test_budget_format_cents(self):
        self.assertEqual(budget.format_cents(0), '$0.00')
        self.assertEqual(budget.format_cents(123456), '$1,234.56')
        self.assertEqual(budget.format_cents(-105), '-$1.05')
        self.assertEqual(budget.format_cents(5), '$0.05')
        self.assertEqual(budget.format_cents(100000000), '$1,000,000.00')

    def test_budget_is_leap(self):
        self.assertEqual(budget.is_leap(2024), True)
        self.assertEqual(budget.is_leap(1900), False)
        self.assertEqual(budget.is_leap(2000), True)
        self.assertEqual(budget.is_leap(2023), False)
        self.assertEqual(budget.is_leap(2400), True)
        self.assertEqual(budget.is_leap(2100), False)

    def test_budget_word_count(self):
        self.assertEqual(budget.word_count('a b'), 2)
        self.assertEqual(budget.word_count('  tea  and   milk '), 3)
        self.assertEqual(budget.word_count(''), 0)
        self.assertEqual(budget.word_count('one'), 1)

    def test_stock_truncate_words(self):
        self.assertEqual(stock.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(stock.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(stock.truncate_words('', 3), '')
        self.assertEqual(stock.truncate_words('one two three', 1), 'one...')

    def test_stock_parse_duration(self):
        self.assertEqual(stock.parse_duration('1h30m'), 5400)
        self.assertEqual(stock.parse_duration('45s'), 45)
        self.assertEqual(stock.parse_duration('2h'), 7200)
        self.assertEqual(stock.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            stock.parse_duration('')
        with self.assertRaises(ValueError):
            stock.parse_duration('5x')
        self.assertEqual(stock.parse_duration('10m5s'), 605)

    def test_stock_paginate(self):
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(stock.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            stock.paginate([1, 2], 0, 2)

    def test_report_mast_view(self):
        self.assertEqual(report.mast_view([(1, 3), (3, 5)]), {'mast_view': [(1, 5)]})
        self.assertEqual(report.mast_view([(5, 6), (1, 2)]), {'mast_view': [(1, 2), (5, 6)]})
        self.assertEqual(report.mast_view([(1, 10), (2, 3)]), {'mast_view': [(1, 10)]})
        self.assertEqual(report.mast_view([]), {'mast_view': []})
        self.assertEqual(report.mast_view([(4, 8), (1, 5)]), {'mast_view': [(1, 8)]})

    def test_report_barge_summary(self):
        self.assertEqual(report.barge_summary('OrderTotal'), {'barge_summary': 'order_total'})
        self.assertEqual(report.barge_summary('plain'), {'barge_summary': 'plain'})
        self.assertEqual(report.barge_summary('A'), {'barge_summary': 'a'})
        self.assertEqual(report.barge_summary('ShipToCity'), {'barge_summary': 'ship_to_city'})

    def test_report_harbor_row(self):
        self.assertEqual(report.harbor_row([3, 1, 2]), {'harbor_row': 2})
        self.assertEqual(report.harbor_row([4, 1, 3, 2]), {'harbor_row': 2.5})
        self.assertEqual(report.harbor_row([5]), {'harbor_row': 5})
        self.assertEqual(report.harbor_row([1, 2]), {'harbor_row': 1.5})
        self.assertEqual(report.harbor_row([10, 2, 38, 23, 38, 23]), {'harbor_row': 23.0})
        with self.assertRaises(ValueError):
            report.harbor_row([])

    def test_report_anchor_row(self):
        self.assertEqual(report.anchor_row(5, [0, 5, 10]), {'anchor_row': 2})
        self.assertEqual(report.anchor_row(-1, [0, 5, 10]), {'anchor_row': 0})
        self.assertEqual(report.anchor_row(12, [0, 5, 10]), {'anchor_row': 3})
        self.assertEqual(report.anchor_row(0, [0, 5, 10]), {'anchor_row': 1})
        self.assertEqual(report.anchor_row(7, []), {'anchor_row': 0})

    def test_report_rope_line(self):
        self.assertEqual(report.rope_line('a b'), {'rope_line': 2})
        self.assertEqual(report.rope_line('  tea  and   milk '), {'rope_line': 3})
        self.assertEqual(report.rope_line(''), {'rope_line': 0})
        self.assertEqual(report.rope_line('one'), {'rope_line': 1})
