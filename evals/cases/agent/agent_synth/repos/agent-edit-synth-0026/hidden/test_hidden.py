import unittest

from quarry import orders
from quarry import ledger


class Hidden(unittest.TestCase):
    def test_orders_weighted_mean(self):
        self.assertEqual(orders.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(orders.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(orders.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            orders.weighted_mean([5, 5], [0, 0])
        self.assertEqual(orders.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_orders_merge_ranges(self):
        self.assertEqual(orders.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(orders.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(orders.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(orders.merge_ranges([]), [])
        self.assertEqual(orders.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_ledger_word_count(self):
        self.assertEqual(ledger.word_count('a b'), 2)
        self.assertEqual(ledger.word_count('  tea  and   milk '), 3)
        self.assertEqual(ledger.word_count(''), 0)
        self.assertEqual(ledger.word_count('one'), 1)

    def test_ledger_grade(self):
        self.assertEqual(ledger.grade(95), 'A')
        self.assertEqual(ledger.grade(90), 'A')
        self.assertEqual(ledger.grade(85), 'B')
        self.assertEqual(ledger.grade(80), 'B')
        self.assertEqual(ledger.grade(61), 'D')
        self.assertEqual(ledger.grade(59), 'F')
        self.assertEqual(ledger.grade(0), 'F')

    def test_ledger_parse_duration(self):
        self.assertEqual(ledger.parse_duration('1h30m'), 5400)
        self.assertEqual(ledger.parse_duration('45s'), 45)
        self.assertEqual(ledger.parse_duration('2h'), 7200)
        self.assertEqual(ledger.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            ledger.parse_duration('')
        with self.assertRaises(ValueError):
            ledger.parse_duration('5x')
        self.assertEqual(ledger.parse_duration('10m5s'), 605)

    def test_feature(self):
        self.assertEqual(ledger.word_count('a tea and milk', min_length=3), 3)
        self.assertEqual(ledger.word_count('go on', min_length=5), 0)
