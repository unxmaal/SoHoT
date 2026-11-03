import unittest

from wharf import routes


class Routes(unittest.TestCase):
    def test_crate_check(self):
        self.assertEqual(routes.crate_check(0), {'crate_check': '$0.00'})
        self.assertEqual(routes.crate_check(123456), {'crate_check': '$1,234.56'})

    def test_paginate(self):
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_is_leap(self):
        self.assertEqual(routes.is_leap(2024), True)
        self.assertEqual(routes.is_leap(1900), False)
