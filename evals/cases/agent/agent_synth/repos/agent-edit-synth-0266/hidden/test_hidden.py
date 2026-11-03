import unittest

from atlas import pricing
from atlas import tickets
from atlas import ledger


class Hidden(unittest.TestCase):
    def test_pricing_bucket(self):
        self.assertEqual(pricing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(pricing.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(pricing.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(pricing.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(pricing.bucket(7, []), 0)

    def test_pricing_invert(self):
        self.assertEqual(pricing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(pricing.invert({}), {})
        self.assertEqual(pricing.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(pricing.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_pricing_format_cents(self):
        self.assertEqual(pricing.format_cents(0), '$0.00')
        self.assertEqual(pricing.format_cents(123456), '$1,234.56')
        self.assertEqual(pricing.format_cents(-105), '-$1.05')
        self.assertEqual(pricing.format_cents(5), '$0.05')
        self.assertEqual(pricing.format_cents(100000000), '$1,000,000.00')

    def test_tickets_truncate_words(self):
        self.assertEqual(tickets.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(tickets.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(tickets.truncate_words('', 3), '')
        self.assertEqual(tickets.truncate_words('one two three', 1), 'one...')

    def test_tickets_percent_change(self):
        self.assertEqual(tickets.percent_change(50, 75), 50.0)
        self.assertEqual(tickets.percent_change(200, 150), -25.0)
        self.assertEqual(tickets.percent_change(80, 80), 0.0)
        self.assertEqual(tickets.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            tickets.percent_change(0, 5)
        self.assertEqual(tickets.percent_change(-10, -5), -50.0)

    def test_ledger_rle(self):
        self.assertEqual(ledger.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(ledger.rle(''), [])
        self.assertEqual(ledger.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(ledger.rle('zz'), [('z', 2)])

    def test_ledger_moving_average(self):
        self.assertEqual(ledger.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(ledger.moving_average([5], 1), [5.0])
        self.assertEqual(ledger.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(ledger.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            ledger.moving_average([1, 2], 0)

    def test_feature(self):
        self.assertEqual(pricing.format_cents(123456, symbol='GBP '), 'GBP 1,234.56')
        self.assertEqual(pricing.format_cents(-105, symbol='EUR '), '-EUR 1.05')
