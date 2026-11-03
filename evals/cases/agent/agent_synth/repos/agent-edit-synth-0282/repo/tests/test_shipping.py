import unittest

from harbor import shipping


class Shipping(unittest.TestCase):
    def test_median(self):
        self.assertEqual(shipping.median([3, 1, 2]), 2)
        self.assertEqual(shipping.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(shipping.median([5]), 5)

    def test_moving_average(self):
        self.assertEqual(shipping.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(shipping.moving_average([5], 1), [5.0])
        self.assertEqual(shipping.moving_average([1, 2, 3], 3), [2.0])

    def test_grade(self):
        self.assertEqual(shipping.grade(95), 'A')
        self.assertEqual(shipping.grade(90), 'A')
        self.assertEqual(shipping.grade(85), 'B')
