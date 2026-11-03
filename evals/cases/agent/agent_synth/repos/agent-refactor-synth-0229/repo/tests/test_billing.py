import unittest

from beacon import billing


class Billing(unittest.TestCase):
    def test_mast_line(self):
        self.assertEqual(billing.mast_line('OrderTotal'), {'mast_line': 'order_total'})
        self.assertEqual(billing.mast_line('plain'), {'mast_line': 'plain'})

    def test_top_n(self):
        self.assertEqual(billing.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(billing.top_n({'a': 1}, 5), ['a'])
