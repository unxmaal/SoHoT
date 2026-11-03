import unittest

from compass import kitchen


class Kitchen(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(kitchen.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(kitchen.moving_average([5], 1), [5.0])
        self.assertEqual(kitchen.moving_average([1, 2, 3], 3), [2.0])

    def test_is_leap(self):
        self.assertEqual(kitchen.is_leap(2024), True)
        self.assertEqual(kitchen.is_leap(1900), False)
        self.assertEqual(kitchen.is_leap(2000), True)
