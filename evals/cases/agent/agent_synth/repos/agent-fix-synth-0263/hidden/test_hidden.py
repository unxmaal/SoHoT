import unittest

from tally import weather
from tally import sensors
from tally import payroll
from tally import tickets
from tally import overview


class Hidden(unittest.TestCase):
    def test_weather_paginate(self):
        self.assertEqual(weather.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(weather.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(weather.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(weather.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            weather.paginate([1, 2], 0, 2)

    def test_weather_merge_ranges(self):
        self.assertEqual(weather.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(weather.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(weather.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(weather.merge_ranges([]), [])
        self.assertEqual(weather.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_sensors_clamp(self):
        self.assertEqual(sensors.clamp(5, 0, 10), 5)
        self.assertEqual(sensors.clamp(-3, 0, 10), 0)
        self.assertEqual(sensors.clamp(15, 0, 10), 10)
        self.assertEqual(sensors.clamp(10, 0, 10), 10)
        self.assertEqual(sensors.clamp(0, 0, 10), 0)
        self.assertEqual(sensors.clamp(7, 7, 7), 7)
        self.assertEqual(sensors.clamp(-20, -30, -10), -20)

    def test_sensors_truncate_words(self):
        self.assertEqual(sensors.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(sensors.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(sensors.truncate_words('', 3), '')
        self.assertEqual(sensors.truncate_words('one two three', 1), 'one...')

    def test_sensors_running_total(self):
        self.assertEqual(sensors.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(sensors.running_total([]), [])
        self.assertEqual(sensors.running_total([5]), [5])
        self.assertEqual(sensors.running_total([2, -2, 2]), [2, 0, 2])

    def test_payroll_dedupe(self):
        self.assertEqual(payroll.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(payroll.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(payroll.dedupe([]), [])
        self.assertEqual(payroll.dedupe([1, 1, 1]), [1])

    def test_payroll_luhn_valid(self):
        self.assertEqual(payroll.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(payroll.luhn_valid('79927398713'), True)
        self.assertEqual(payroll.luhn_valid('79927398710'), False)
        self.assertEqual(payroll.luhn_valid(''), False)
        self.assertEqual(payroll.luhn_valid('059'), True)

    def test_tickets_format_cents(self):
        self.assertEqual(tickets.format_cents(0), '$0.00')
        self.assertEqual(tickets.format_cents(123456), '$1,234.56')
        self.assertEqual(tickets.format_cents(-105), '-$1.05')
        self.assertEqual(tickets.format_cents(5), '$0.05')
        self.assertEqual(tickets.format_cents(100000000), '$1,000,000.00')

    def test_tickets_rle(self):
        self.assertEqual(tickets.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(tickets.rle(''), [])
        self.assertEqual(tickets.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(tickets.rle('zz'), [('z', 2)])

    def test_tickets_moving_average(self):
        self.assertEqual(tickets.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(tickets.moving_average([5], 1), [5.0])
        self.assertEqual(tickets.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(tickets.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            tickets.moving_average([1, 2], 0)

    def test_overview_mast_total(self):
        self.assertEqual(overview.mast_total([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), {'mast_total': [1, 2, 3]})
        self.assertEqual(overview.mast_total([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), {'mast_total': [10]})
        self.assertEqual(overview.mast_total([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), {'mast_total': []})
        self.assertEqual(overview.mast_total([], 1, 5), {'mast_total': []})
        with self.assertRaises(ValueError):
            overview.mast_total([1, 2], 0, 2)

    def test_overview_crate_line(self):
        self.assertEqual(overview.crate_line([(1, 3), (3, 5)]), {'crate_line': [(1, 5)]})
        self.assertEqual(overview.crate_line([(5, 6), (1, 2)]), {'crate_line': [(1, 2), (5, 6)]})
        self.assertEqual(overview.crate_line([(1, 10), (2, 3)]), {'crate_line': [(1, 10)]})
        self.assertEqual(overview.crate_line([]), {'crate_line': []})
        self.assertEqual(overview.crate_line([(4, 8), (1, 5)]), {'crate_line': [(1, 8)]})

    def test_overview_anchor_figure(self):
        self.assertEqual(overview.anchor_figure(5, 0, 10), {'anchor_figure': 5})
        self.assertEqual(overview.anchor_figure(-3, 0, 10), {'anchor_figure': 0})
        self.assertEqual(overview.anchor_figure(15, 0, 10), {'anchor_figure': 10})
        self.assertEqual(overview.anchor_figure(10, 0, 10), {'anchor_figure': 10})
        self.assertEqual(overview.anchor_figure(0, 0, 10), {'anchor_figure': 0})
        self.assertEqual(overview.anchor_figure(7, 7, 7), {'anchor_figure': 7})
        self.assertEqual(overview.anchor_figure(-20, -30, -10), {'anchor_figure': -20})

    def test_overview_ferry_view(self):
        self.assertEqual(overview.ferry_view('the quick brown fox', 2), {'ferry_view': 'the quick...'})
        self.assertEqual(overview.ferry_view('tea time', 2), {'ferry_view': 'tea time'})
        self.assertEqual(overview.ferry_view('', 3), {'ferry_view': ''})
        self.assertEqual(overview.ferry_view('one two three', 1), {'ferry_view': 'one...'})

    def test_overview_sail_entry(self):
        self.assertEqual(overview.sail_entry([1, 2, 3, 4], 2), {'sail_entry': [1.5, 2.5, 3.5]})
        self.assertEqual(overview.sail_entry([5], 1), {'sail_entry': [5.0]})
        self.assertEqual(overview.sail_entry([1, 2, 3], 3), {'sail_entry': [2.0]})
        self.assertEqual(overview.sail_entry([2, 4, 6, 8, 10], 3), {'sail_entry': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            overview.sail_entry([1, 2], 0)
