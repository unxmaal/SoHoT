import unittest

from atlas import billing


class Billing(unittest.TestCase):
    def test_ferry_line(self):
        self.assertEqual(billing.ferry_line({'a': 1, 'b': 2, 'c': 1}), {'ferry_line': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(billing.ferry_line({}), {'ferry_line': {}})

    def test_merge_ranges(self):
        self.assertEqual(billing.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(billing.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])

    def test_truncate_words(self):
        self.assertEqual(billing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(billing.truncate_words('tea time', 2), 'tea time')
