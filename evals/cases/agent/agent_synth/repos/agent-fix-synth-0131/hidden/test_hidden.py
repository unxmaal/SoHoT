import unittest

from granary import tickets
from granary import pricing
from granary import billing


class Hidden(unittest.TestCase):
    def test_tickets_dedupe(self):
        self.assertEqual(tickets.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(tickets.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(tickets.dedupe([]), [])
        self.assertEqual(tickets.dedupe([1, 1, 1]), [1])

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

    def test_pricing_truncate_words(self):
        self.assertEqual(pricing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(pricing.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(pricing.truncate_words('', 3), '')
        self.assertEqual(pricing.truncate_words('one two three', 1), 'one...')

    def test_pricing_weighted_mean(self):
        self.assertEqual(pricing.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(pricing.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(pricing.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            pricing.weighted_mean([5, 5], [0, 0])
        self.assertEqual(pricing.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_pricing_chunk(self):
        self.assertEqual(pricing.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(pricing.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(pricing.chunk([], 3), [])
        self.assertEqual(pricing.chunk(['a'], 1), [['a']])
        self.assertEqual(pricing.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            pricing.chunk([1, 2], 0)

    def test_billing_is_leap(self):
        self.assertEqual(billing.is_leap(2024), True)
        self.assertEqual(billing.is_leap(1900), False)
        self.assertEqual(billing.is_leap(2000), True)
        self.assertEqual(billing.is_leap(2023), False)
        self.assertEqual(billing.is_leap(2400), True)
        self.assertEqual(billing.is_leap(2100), False)

    def test_billing_bucket(self):
        self.assertEqual(billing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(billing.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(billing.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(billing.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(billing.bucket(7, []), 0)
