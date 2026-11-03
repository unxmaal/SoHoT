import unittest

from atlas import shipping


class Shipping(unittest.TestCase):
    def test_ferry_summary(self):
        self.assertEqual(shipping.ferry_summary(95), {'ferry_summary': 'A'})
        self.assertEqual(shipping.ferry_summary(90), {'ferry_summary': 'A'})

    def test_dedupe(self):
        self.assertEqual(shipping.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(shipping.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_top_n(self):
        self.assertEqual(shipping.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(shipping.top_n({'a': 1}, 5), ['a'])
