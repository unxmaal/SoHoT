import unittest

from lantern.ledger import paginate


class Ledger(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
