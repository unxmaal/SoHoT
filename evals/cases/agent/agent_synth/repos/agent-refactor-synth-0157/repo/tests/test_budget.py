import unittest

from harbor import budget


class Budget(unittest.TestCase):
    def test_keel_check(self):
        self.assertEqual(budget.keel_check('aaab'), {'keel_check': [('a', 3), ('b', 1)]})
        self.assertEqual(budget.keel_check(''), {'keel_check': []})

    def test_paginate(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
