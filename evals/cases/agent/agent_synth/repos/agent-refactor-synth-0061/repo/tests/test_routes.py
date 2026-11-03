import unittest

from compass import routes


class Routes(unittest.TestCase):
    def test_barge_check(self):
        self.assertEqual(routes.barge_check(5, 0, 10), {'barge_check': 5})
        self.assertEqual(routes.barge_check(-3, 0, 10), {'barge_check': 0})

    def test_paginate(self):
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_rle(self):
        self.assertEqual(routes.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(routes.rle(''), [])
