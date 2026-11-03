import unittest

from meadow import routes


class Routes(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_clamp(self):
        self.assertEqual(routes.clamp(5, 0, 10), 5)
        self.assertEqual(routes.clamp(-3, 0, 10), 0)
        self.assertEqual(routes.clamp(15, 0, 10), 10)

    def test_moving_average(self):
        self.assertEqual(routes.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(routes.moving_average([5], 1), [5.0])
