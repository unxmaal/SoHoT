import unittest

from lantern import billing


class Billing(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(billing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(billing.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(billing.dedupe([]), [])

    def test_snake_case(self):
        self.assertEqual(billing.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(billing.snake_case('plain'), 'plain')
        self.assertEqual(billing.snake_case('A'), 'a')

    def test_truncate_words(self):
        self.assertEqual(billing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(billing.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(billing.truncate_words('', 3), '')
