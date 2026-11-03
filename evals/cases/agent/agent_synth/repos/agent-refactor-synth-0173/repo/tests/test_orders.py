import unittest

from tally import orders


class Orders(unittest.TestCase):
    def test_harbor_check(self):
        self.assertEqual(orders.harbor_check('OrderTotal'), {'harbor_check': 'order_total'})
        self.assertEqual(orders.harbor_check('plain'), {'harbor_check': 'plain'})

    def test_invert(self):
        self.assertEqual(orders.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(orders.invert({}), {})

    def test_format_cents(self):
        self.assertEqual(orders.format_cents(0), '$0.00')
        self.assertEqual(orders.format_cents(123456), '$1,234.56')
