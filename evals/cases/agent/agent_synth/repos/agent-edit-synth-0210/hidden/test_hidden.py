import unittest

from lantern import billing
from lantern import tickets


class Hidden(unittest.TestCase):
    def test_billing_dedupe(self):
        self.assertEqual(billing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(billing.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(billing.dedupe([]), [])
        self.assertEqual(billing.dedupe([1, 1, 1]), [1])

    def test_billing_snake_case(self):
        self.assertEqual(billing.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(billing.snake_case('plain'), 'plain')
        self.assertEqual(billing.snake_case('A'), 'a')
        self.assertEqual(billing.snake_case('ShipToCity'), 'ship_to_city')

    def test_billing_truncate_words(self):
        self.assertEqual(billing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(billing.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(billing.truncate_words('', 3), '')
        self.assertEqual(billing.truncate_words('one two three', 1), 'one...')

    def test_tickets_luhn_valid(self):
        self.assertEqual(tickets.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(tickets.luhn_valid('79927398713'), True)
        self.assertEqual(tickets.luhn_valid('79927398710'), False)
        self.assertEqual(tickets.luhn_valid(''), False)
        self.assertEqual(tickets.luhn_valid('059'), True)

    def test_tickets_weighted_mean(self):
        self.assertEqual(tickets.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(tickets.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(tickets.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            tickets.weighted_mean([5, 5], [0, 0])
        self.assertEqual(tickets.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_feature(self):
        self.assertEqual(billing.dedupe(['Tea', 'tea', 'Milk', 'TEA'], ignore_case=True), ['Tea', 'Milk'])
        self.assertEqual(billing.dedupe(['a', 'A'], ignore_case=True), ['a'])
