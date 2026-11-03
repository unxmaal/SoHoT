import unittest

from wharf import orders
from wharf import ledger
from wharf import billing


class Hidden(unittest.TestCase):
    def test_orders_median(self):
        self.assertEqual(orders.median([3, 1, 2]), 2)
        self.assertEqual(orders.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(orders.median([5]), 5)
        self.assertEqual(orders.median([1, 2]), 1.5)
        self.assertEqual(orders.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            orders.median([])

    def test_orders_word_count(self):
        self.assertEqual(orders.word_count('a b'), 2)
        self.assertEqual(orders.word_count('  tea  and   milk '), 3)
        self.assertEqual(orders.word_count(''), 0)
        self.assertEqual(orders.word_count('one'), 1)

    def test_orders_is_leap(self):
        self.assertEqual(orders.is_leap(2024), True)
        self.assertEqual(orders.is_leap(1900), False)
        self.assertEqual(orders.is_leap(2000), True)
        self.assertEqual(orders.is_leap(2023), False)
        self.assertEqual(orders.is_leap(2400), True)
        self.assertEqual(orders.is_leap(2100), False)

    def test_ledger_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)
        self.assertEqual(ledger.clamp(15, 0, 10), 10)
        self.assertEqual(ledger.clamp(10, 0, 10), 10)
        self.assertEqual(ledger.clamp(0, 0, 10), 0)
        self.assertEqual(ledger.clamp(7, 7, 7), 7)
        self.assertEqual(ledger.clamp(-20, -30, -10), -20)

    def test_ledger_dedupe(self):
        self.assertEqual(ledger.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(ledger.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(ledger.dedupe([]), [])
        self.assertEqual(ledger.dedupe([1, 1, 1]), [1])

    def test_billing_paginate(self):
        self.assertEqual(billing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(billing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(billing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(billing.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            billing.paginate([1, 2], 0, 2)

    def test_billing_truncate_words(self):
        self.assertEqual(billing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(billing.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(billing.truncate_words('', 3), '')
        self.assertEqual(billing.truncate_words('one two three', 1), 'one...')
