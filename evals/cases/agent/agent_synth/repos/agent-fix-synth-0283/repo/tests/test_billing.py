import unittest

from tally import billing


class Billing(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(billing.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(billing.snake_case('plain'), 'plain')
        self.assertEqual(billing.snake_case('A'), 'a')

    def test_top_n(self):
        self.assertEqual(billing.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(billing.top_n({'a': 1}, 5), ['a'])

    def test_rle(self):
        self.assertEqual(billing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(billing.rle(''), [])
