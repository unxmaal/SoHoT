import unittest

from harbor import catalog
from harbor import stock
from harbor import ledger
from harbor import survey
from harbor import rosters


class Hidden(unittest.TestCase):
    def test_catalog_paginate(self):
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(catalog.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            catalog.paginate([1, 2], 0, 2)

    def test_catalog_dedupe(self):
        self.assertEqual(catalog.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(catalog.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(catalog.dedupe([]), [])
        self.assertEqual(catalog.dedupe([1, 1, 1]), [1])

    def test_catalog_median(self):
        self.assertEqual(catalog.median([3, 1, 2]), 2)
        self.assertEqual(catalog.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(catalog.median([5]), 5)
        self.assertEqual(catalog.median([1, 2]), 1.5)
        self.assertEqual(catalog.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            catalog.median([])

    def test_stock_invert(self):
        self.assertEqual(stock.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(stock.invert({}), {})
        self.assertEqual(stock.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(stock.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_stock_is_leap(self):
        self.assertEqual(stock.is_leap(2024), True)
        self.assertEqual(stock.is_leap(1900), False)
        self.assertEqual(stock.is_leap(2000), True)
        self.assertEqual(stock.is_leap(2023), False)
        self.assertEqual(stock.is_leap(2400), True)
        self.assertEqual(stock.is_leap(2100), False)

    def test_ledger_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(ledger.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(ledger.merge_ranges([]), [])
        self.assertEqual(ledger.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_ledger_weighted_mean(self):
        self.assertEqual(ledger.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(ledger.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(ledger.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            ledger.weighted_mean([5, 5], [0, 0])
        self.assertEqual(ledger.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_ledger_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)
        self.assertEqual(ledger.clamp(15, 0, 10), 10)
        self.assertEqual(ledger.clamp(10, 0, 10), 10)
        self.assertEqual(ledger.clamp(0, 0, 10), 0)
        self.assertEqual(ledger.clamp(7, 7, 7), 7)
        self.assertEqual(ledger.clamp(-20, -30, -10), -20)

    def test_survey_moving_average(self):
        self.assertEqual(survey.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(survey.moving_average([5], 1), [5.0])
        self.assertEqual(survey.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(survey.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            survey.moving_average([1, 2], 0)

    def test_survey_top_n(self):
        self.assertEqual(survey.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(survey.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(survey.top_n({}, 2), [])
        self.assertEqual(survey.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_rosters_format_cents(self):
        self.assertEqual(rosters.format_cents(0), '$0.00')
        self.assertEqual(rosters.format_cents(123456), '$1,234.56')
        self.assertEqual(rosters.format_cents(-105), '-$1.05')
        self.assertEqual(rosters.format_cents(5), '$0.05')
        self.assertEqual(rosters.format_cents(100000000), '$1,000,000.00')

    def test_rosters_truncate_words(self):
        self.assertEqual(rosters.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(rosters.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(rosters.truncate_words('', 3), '')
        self.assertEqual(rosters.truncate_words('one two three', 1), 'one...')
