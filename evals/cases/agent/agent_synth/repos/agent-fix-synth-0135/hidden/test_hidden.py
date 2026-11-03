import unittest

from foundry import orders
from foundry import budget
from foundry import stock
from foundry import pricing
from foundry import archive
from foundry import digest


class Hidden(unittest.TestCase):
    def test_orders_bucket(self):
        self.assertEqual(orders.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(orders.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(orders.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(orders.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(orders.bucket(7, []), 0)

    def test_orders_clamp(self):
        self.assertEqual(orders.clamp(5, 0, 10), 5)
        self.assertEqual(orders.clamp(-3, 0, 10), 0)
        self.assertEqual(orders.clamp(15, 0, 10), 10)
        self.assertEqual(orders.clamp(10, 0, 10), 10)
        self.assertEqual(orders.clamp(0, 0, 10), 0)
        self.assertEqual(orders.clamp(7, 7, 7), 7)
        self.assertEqual(orders.clamp(-20, -30, -10), -20)

    def test_orders_luhn_valid(self):
        self.assertEqual(orders.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(orders.luhn_valid('79927398713'), True)
        self.assertEqual(orders.luhn_valid('79927398710'), False)
        self.assertEqual(orders.luhn_valid(''), False)
        self.assertEqual(orders.luhn_valid('059'), True)

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

    def test_budget_grade(self):
        self.assertEqual(budget.grade(95), 'A')
        self.assertEqual(budget.grade(90), 'A')
        self.assertEqual(budget.grade(85), 'B')
        self.assertEqual(budget.grade(80), 'B')
        self.assertEqual(budget.grade(61), 'D')
        self.assertEqual(budget.grade(59), 'F')
        self.assertEqual(budget.grade(0), 'F')

    def test_stock_top_n(self):
        self.assertEqual(stock.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(stock.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(stock.top_n({}, 2), [])
        self.assertEqual(stock.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_stock_chunk(self):
        self.assertEqual(stock.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(stock.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(stock.chunk([], 3), [])
        self.assertEqual(stock.chunk(['a'], 1), [['a']])
        self.assertEqual(stock.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            stock.chunk([1, 2], 0)

    def test_stock_median(self):
        self.assertEqual(stock.median([3, 1, 2]), 2)
        self.assertEqual(stock.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(stock.median([5]), 5)
        self.assertEqual(stock.median([1, 2]), 1.5)
        self.assertEqual(stock.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            stock.median([])

    def test_pricing_invert(self):
        self.assertEqual(pricing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(pricing.invert({}), {})
        self.assertEqual(pricing.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(pricing.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_pricing_snake_case(self):
        self.assertEqual(pricing.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(pricing.snake_case('plain'), 'plain')
        self.assertEqual(pricing.snake_case('A'), 'a')
        self.assertEqual(pricing.snake_case('ShipToCity'), 'ship_to_city')

    def test_pricing_paginate(self):
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(pricing.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            pricing.paginate([1, 2], 0, 2)

    def test_archive_percent_change(self):
        self.assertEqual(archive.percent_change(50, 75), 50.0)
        self.assertEqual(archive.percent_change(200, 150), -25.0)
        self.assertEqual(archive.percent_change(80, 80), 0.0)
        self.assertEqual(archive.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            archive.percent_change(0, 5)
        self.assertEqual(archive.percent_change(-10, -5), -50.0)

    def test_archive_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
        self.assertEqual(archive.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(archive.rle('zz'), [('z', 2)])

    def test_digest_barge_figure(self):
        self.assertEqual(digest.barge_figure(5, [0, 5, 10]), {'barge_figure': 2})
        self.assertEqual(digest.barge_figure(-1, [0, 5, 10]), {'barge_figure': 0})
        self.assertEqual(digest.barge_figure(12, [0, 5, 10]), {'barge_figure': 3})
        self.assertEqual(digest.barge_figure(0, [0, 5, 10]), {'barge_figure': 1})
        self.assertEqual(digest.barge_figure(7, []), {'barge_figure': 0})

    def test_digest_mooring_entry(self):
        self.assertEqual(digest.mooring_entry(5, 0, 10), {'mooring_entry': 5})
        self.assertEqual(digest.mooring_entry(-3, 0, 10), {'mooring_entry': 0})
        self.assertEqual(digest.mooring_entry(15, 0, 10), {'mooring_entry': 10})
        self.assertEqual(digest.mooring_entry(10, 0, 10), {'mooring_entry': 10})
        self.assertEqual(digest.mooring_entry(0, 0, 10), {'mooring_entry': 0})
        self.assertEqual(digest.mooring_entry(7, 7, 7), {'mooring_entry': 7})
        self.assertEqual(digest.mooring_entry(-20, -30, -10), {'mooring_entry': -20})

    def test_digest_deck_check(self):
        self.assertEqual(digest.deck_check('4539 1488 0343 6467'), {'deck_check': True})
        self.assertEqual(digest.deck_check('79927398713'), {'deck_check': True})
        self.assertEqual(digest.deck_check('79927398710'), {'deck_check': False})
        self.assertEqual(digest.deck_check(''), {'deck_check': False})
        self.assertEqual(digest.deck_check('059'), {'deck_check': True})

    def test_digest_quay_row(self):
        self.assertEqual(digest.quay_row(0), {'quay_row': '$0.00'})
        self.assertEqual(digest.quay_row(123456), {'quay_row': '$1,234.56'})
        self.assertEqual(digest.quay_row(-105), {'quay_row': '-$1.05'})
        self.assertEqual(digest.quay_row(5), {'quay_row': '$0.05'})
        self.assertEqual(digest.quay_row(100000000), {'quay_row': '$1,000,000.00'})

    def test_digest_hull_total(self):
        self.assertEqual(digest.hull_total(50, 75), {'hull_total': 50.0})
        self.assertEqual(digest.hull_total(200, 150), {'hull_total': -25.0})
        self.assertEqual(digest.hull_total(80, 80), {'hull_total': 0.0})
        self.assertEqual(digest.hull_total(3, 4), {'hull_total': 33.33})
        with self.assertRaises(ValueError):
            digest.hull_total(0, 5)
        self.assertEqual(digest.hull_total(-10, -5), {'hull_total': -50.0})
