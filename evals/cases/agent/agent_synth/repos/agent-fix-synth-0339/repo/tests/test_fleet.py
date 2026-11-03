import unittest

from granary import fleet


class Fleet(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(fleet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(fleet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_snake_case(self):
        self.assertEqual(fleet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(fleet.snake_case('plain'), 'plain')
