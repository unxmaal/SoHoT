import unittest

from compass import orders


class Orders(unittest.TestCase):
    def test_keel_check(self):
        self.assertEqual(orders.keel_check(95), {'keel_check': 'A'})
        self.assertEqual(orders.keel_check(90), {'keel_check': 'A'})

    def test_top_n(self):
        self.assertEqual(orders.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(orders.top_n({'a': 1}, 5), ['a'])
