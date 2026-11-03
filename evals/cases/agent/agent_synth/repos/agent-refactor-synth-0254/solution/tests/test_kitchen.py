import unittest

from depot.kitchen import coalesce
from depot import kitchen


class Kitchen(unittest.TestCase):
    def test_coalesce(self):
        self.assertEqual(coalesce([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(coalesce([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(coalesce([(1, 10), (2, 3)]), [(1, 10)])

    def test_moving_average(self):
        self.assertEqual(kitchen.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(kitchen.moving_average([5], 1), [5.0])
