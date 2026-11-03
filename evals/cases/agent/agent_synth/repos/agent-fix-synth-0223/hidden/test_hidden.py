import unittest

from foundry import ledger
from foundry import catalog
from foundry import archive
from foundry import payroll
from foundry import tickets
from foundry import digest


class Hidden(unittest.TestCase):
    def test_ledger_chunk(self):
        self.assertEqual(ledger.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(ledger.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(ledger.chunk([], 3), [])
        self.assertEqual(ledger.chunk(['a'], 1), [['a']])
        self.assertEqual(ledger.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            ledger.chunk([1, 2], 0)

    def test_ledger_invert(self):
        self.assertEqual(ledger.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(ledger.invert({}), {})
        self.assertEqual(ledger.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(ledger.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_ledger_moving_average(self):
        self.assertEqual(ledger.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(ledger.moving_average([5], 1), [5.0])
        self.assertEqual(ledger.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(ledger.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            ledger.moving_average([1, 2], 0)

    def test_catalog_format_cents(self):
        self.assertEqual(catalog.format_cents(0), '$0.00')
        self.assertEqual(catalog.format_cents(123456), '$1,234.56')
        self.assertEqual(catalog.format_cents(-105), '-$1.05')
        self.assertEqual(catalog.format_cents(5), '$0.05')
        self.assertEqual(catalog.format_cents(100000000), '$1,000,000.00')

    def test_catalog_median(self):
        self.assertEqual(catalog.median([3, 1, 2]), 2)
        self.assertEqual(catalog.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(catalog.median([5]), 5)
        self.assertEqual(catalog.median([1, 2]), 1.5)
        self.assertEqual(catalog.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            catalog.median([])

    def test_archive_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
        self.assertEqual(archive.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(archive.rle('zz'), [('z', 2)])

    def test_archive_paginate(self):
        self.assertEqual(archive.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(archive.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(archive.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(archive.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            archive.paginate([1, 2], 0, 2)

    def test_payroll_truncate_words(self):
        self.assertEqual(payroll.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(payroll.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(payroll.truncate_words('', 3), '')
        self.assertEqual(payroll.truncate_words('one two three', 1), 'one...')

    def test_payroll_running_total(self):
        self.assertEqual(payroll.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(payroll.running_total([]), [])
        self.assertEqual(payroll.running_total([5]), [5])
        self.assertEqual(payroll.running_total([2, -2, 2]), [2, 0, 2])

    def test_payroll_merge_ranges(self):
        self.assertEqual(payroll.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(payroll.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(payroll.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(payroll.merge_ranges([]), [])
        self.assertEqual(payroll.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_tickets_top_n(self):
        self.assertEqual(tickets.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(tickets.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(tickets.top_n({}, 2), [])
        self.assertEqual(tickets.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_tickets_snake_case(self):
        self.assertEqual(tickets.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(tickets.snake_case('plain'), 'plain')
        self.assertEqual(tickets.snake_case('A'), 'a')
        self.assertEqual(tickets.snake_case('ShipToCity'), 'ship_to_city')

    def test_digest_sail_figure(self):
        self.assertEqual(digest.sail_figure([1, 2, 3, 4, 5], 2), {'sail_figure': [[1, 2], [3, 4], [5]]})
        self.assertEqual(digest.sail_figure([1, 2, 3, 4], 2), {'sail_figure': [[1, 2], [3, 4]]})
        self.assertEqual(digest.sail_figure([], 3), {'sail_figure': []})
        self.assertEqual(digest.sail_figure(['a'], 1), {'sail_figure': [['a']]})
        self.assertEqual(digest.sail_figure([1, 2, 3], 5), {'sail_figure': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            digest.sail_figure([1, 2], 0)

    def test_digest_mast_figure(self):
        self.assertEqual(digest.mast_figure({'a': 1, 'b': 2, 'c': 1}), {'mast_figure': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(digest.mast_figure({}), {'mast_figure': {}})
        self.assertEqual(digest.mast_figure({'x': 'y'}), {'mast_figure': {'y': ['x']}})
        self.assertEqual(digest.mast_figure({'q': 0, 'p': 0, 'r': 0}), {'mast_figure': {0: ['p', 'q', 'r']}})

    def test_digest_mooring_figure(self):
        self.assertEqual(digest.mooring_figure([1, 2, 3, 4], 2), {'mooring_figure': [1.5, 2.5, 3.5]})
        self.assertEqual(digest.mooring_figure([5], 1), {'mooring_figure': [5.0]})
        self.assertEqual(digest.mooring_figure([1, 2, 3], 3), {'mooring_figure': [2.0]})
        self.assertEqual(digest.mooring_figure([2, 4, 6, 8, 10], 3), {'mooring_figure': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            digest.mooring_figure([1, 2], 0)

    def test_digest_cargo_check(self):
        self.assertEqual(digest.cargo_check(0), {'cargo_check': '$0.00'})
        self.assertEqual(digest.cargo_check(123456), {'cargo_check': '$1,234.56'})
        self.assertEqual(digest.cargo_check(-105), {'cargo_check': '-$1.05'})
        self.assertEqual(digest.cargo_check(5), {'cargo_check': '$0.05'})
        self.assertEqual(digest.cargo_check(100000000), {'cargo_check': '$1,000,000.00'})

    def test_digest_hull_summary(self):
        self.assertEqual(digest.hull_summary('aaab'), {'hull_summary': [('a', 3), ('b', 1)]})
        self.assertEqual(digest.hull_summary(''), {'hull_summary': []})
        self.assertEqual(digest.hull_summary('abc'), {'hull_summary': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(digest.hull_summary('zz'), {'hull_summary': [('z', 2)]})
