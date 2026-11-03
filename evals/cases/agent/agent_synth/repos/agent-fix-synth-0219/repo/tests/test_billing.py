import unittest

from wharf import billing


class Billing(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(billing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(billing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_truncate_words(self):
        self.assertEqual(billing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(billing.truncate_words('tea time', 2), 'tea time')
