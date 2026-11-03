import unittest

from tally import shipping


class Shipping(unittest.TestCase):
    def test_sail_row(self):
        self.assertEqual(shipping.sail_row({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'sail_row': ['milk', 'tea']})
        self.assertEqual(shipping.sail_row({'a': 1}, 5), {'sail_row': ['a']})

    def test_word_count(self):
        self.assertEqual(shipping.word_count('a b'), 2)
        self.assertEqual(shipping.word_count('  tea  and   milk '), 3)

    def test_merge_ranges(self):
        self.assertEqual(shipping.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(shipping.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
