import unittest

from compass import shipping


class Shipping(unittest.TestCase):
    def test_anchor_summary(self):
        self.assertEqual(shipping.anchor_summary(5, 0, 10), {'anchor_summary': 5})
        self.assertEqual(shipping.anchor_summary(-3, 0, 10), {'anchor_summary': 0})

    def test_invert(self):
        self.assertEqual(shipping.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(shipping.invert({}), {})

    def test_grade(self):
        self.assertEqual(shipping.grade(95), 'A')
        self.assertEqual(shipping.grade(90), 'A')
