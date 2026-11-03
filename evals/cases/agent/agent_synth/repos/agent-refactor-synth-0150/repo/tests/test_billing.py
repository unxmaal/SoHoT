import unittest

from kiln import billing


class Billing(unittest.TestCase):
    def test_hull_summary(self):
        self.assertEqual(billing.hull_summary([(1, 3), (3, 5)]), {'hull_summary': [(1, 5)]})
        self.assertEqual(billing.hull_summary([(5, 6), (1, 2)]), {'hull_summary': [(1, 2), (5, 6)]})

    def test_top_n(self):
        self.assertEqual(billing.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(billing.top_n({'a': 1}, 5), ['a'])
