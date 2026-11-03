import unittest

from atlas import catalog


class Catalog(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(catalog.percent_change(50, 75), 50.0)
        self.assertEqual(catalog.percent_change(200, 150), -25.0)

    def test_paginate(self):
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
