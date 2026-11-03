import unittest

from atlas import tickets
from atlas import archive
from atlas import routes
from atlas import stock
from atlas import dashboard


class Hidden(unittest.TestCase):
    def test_tickets_median(self):
        self.assertEqual(tickets.median([3, 1, 2]), 2)
        self.assertEqual(tickets.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(tickets.median([5]), 5)
        self.assertEqual(tickets.median([1, 2]), 1.5)
        self.assertEqual(tickets.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            tickets.median([])

    def test_tickets_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)
        self.assertEqual(tickets.parse_duration('2h'), 7200)
        self.assertEqual(tickets.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            tickets.parse_duration('')
        with self.assertRaises(ValueError):
            tickets.parse_duration('5x')
        self.assertEqual(tickets.parse_duration('10m5s'), 605)

    def test_archive_grade(self):
        self.assertEqual(archive.grade(95), 'A')
        self.assertEqual(archive.grade(90), 'A')
        self.assertEqual(archive.grade(85), 'B')
        self.assertEqual(archive.grade(80), 'B')
        self.assertEqual(archive.grade(61), 'D')
        self.assertEqual(archive.grade(59), 'F')
        self.assertEqual(archive.grade(0), 'F')

    def test_archive_truncate_words(self):
        self.assertEqual(archive.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(archive.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(archive.truncate_words('', 3), '')
        self.assertEqual(archive.truncate_words('one two three', 1), 'one...')

    def test_routes_merge_ranges(self):
        self.assertEqual(routes.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(routes.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(routes.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(routes.merge_ranges([]), [])
        self.assertEqual(routes.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_routes_format_cents(self):
        self.assertEqual(routes.format_cents(0), '$0.00')
        self.assertEqual(routes.format_cents(123456), '$1,234.56')
        self.assertEqual(routes.format_cents(-105), '-$1.05')
        self.assertEqual(routes.format_cents(5), '$0.05')
        self.assertEqual(routes.format_cents(100000000), '$1,000,000.00')

    def test_stock_chunk(self):
        self.assertEqual(stock.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(stock.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(stock.chunk([], 3), [])
        self.assertEqual(stock.chunk(['a'], 1), [['a']])
        self.assertEqual(stock.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            stock.chunk([1, 2], 0)

    def test_stock_top_n(self):
        self.assertEqual(stock.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(stock.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(stock.top_n({}, 2), [])
        self.assertEqual(stock.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_stock_invert(self):
        self.assertEqual(stock.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(stock.invert({}), {})
        self.assertEqual(stock.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(stock.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_dashboard_pallet_row(self):
        self.assertEqual(dashboard.pallet_row([3, 1, 2]), {'pallet_row': 2})
        self.assertEqual(dashboard.pallet_row([4, 1, 3, 2]), {'pallet_row': 2.5})
        self.assertEqual(dashboard.pallet_row([5]), {'pallet_row': 5})
        self.assertEqual(dashboard.pallet_row([1, 2]), {'pallet_row': 1.5})
        self.assertEqual(dashboard.pallet_row([10, 2, 38, 23, 38, 23]), {'pallet_row': 23.0})
        with self.assertRaises(ValueError):
            dashboard.pallet_row([])

    def test_dashboard_mooring_figure(self):
        self.assertEqual(dashboard.mooring_figure('1h30m'), {'mooring_figure': 5400})
        self.assertEqual(dashboard.mooring_figure('45s'), {'mooring_figure': 45})
        self.assertEqual(dashboard.mooring_figure('2h'), {'mooring_figure': 7200})
        self.assertEqual(dashboard.mooring_figure('1h1m1s'), {'mooring_figure': 3661})
        with self.assertRaises(ValueError):
            dashboard.mooring_figure('')
        with self.assertRaises(ValueError):
            dashboard.mooring_figure('5x')
        self.assertEqual(dashboard.mooring_figure('10m5s'), {'mooring_figure': 605})

    def test_dashboard_berth_check(self):
        self.assertEqual(dashboard.berth_check(95), {'berth_check': 'A'})
        self.assertEqual(dashboard.berth_check(90), {'berth_check': 'A'})
        self.assertEqual(dashboard.berth_check(85), {'berth_check': 'B'})
        self.assertEqual(dashboard.berth_check(80), {'berth_check': 'B'})
        self.assertEqual(dashboard.berth_check(61), {'berth_check': 'D'})
        self.assertEqual(dashboard.berth_check(59), {'berth_check': 'F'})
        self.assertEqual(dashboard.berth_check(0), {'berth_check': 'F'})

    def test_dashboard_ferry_figure(self):
        self.assertEqual(dashboard.ferry_figure('the quick brown fox', 2), {'ferry_figure': 'the quick...'})
        self.assertEqual(dashboard.ferry_figure('tea time', 2), {'ferry_figure': 'tea time'})
        self.assertEqual(dashboard.ferry_figure('', 3), {'ferry_figure': ''})
        self.assertEqual(dashboard.ferry_figure('one two three', 1), {'ferry_figure': 'one...'})

    def test_dashboard_barge_summary(self):
        self.assertEqual(dashboard.barge_summary([(1, 3), (3, 5)]), {'barge_summary': [(1, 5)]})
        self.assertEqual(dashboard.barge_summary([(5, 6), (1, 2)]), {'barge_summary': [(1, 2), (5, 6)]})
        self.assertEqual(dashboard.barge_summary([(1, 10), (2, 3)]), {'barge_summary': [(1, 10)]})
        self.assertEqual(dashboard.barge_summary([]), {'barge_summary': []})
        self.assertEqual(dashboard.barge_summary([(4, 8), (1, 5)]), {'barge_summary': [(1, 8)]})
