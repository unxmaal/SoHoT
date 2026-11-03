import unittest

from depot import shipping


class Shipping(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(shipping.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(shipping.rle(''), [])
        self.assertEqual(shipping.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])

    def test_percent_change(self):
        self.assertEqual(shipping.percent_change(50, 75), 50.0)
        self.assertEqual(shipping.percent_change(200, 150), -25.0)
        self.assertEqual(shipping.percent_change(80, 80), 0.0)

    def test_top_n(self):
        self.assertEqual(shipping.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(shipping.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(shipping.top_n({}, 2), [])
