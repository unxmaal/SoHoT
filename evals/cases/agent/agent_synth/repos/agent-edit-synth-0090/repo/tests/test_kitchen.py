import unittest

from meadow import kitchen


class Kitchen(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(kitchen.grade(95), 'A')
        self.assertEqual(kitchen.grade(90), 'A')
        self.assertEqual(kitchen.grade(85), 'B')

    def test_clamp(self):
        self.assertEqual(kitchen.clamp(5, 0, 10), 5)
        self.assertEqual(kitchen.clamp(-3, 0, 10), 0)
        self.assertEqual(kitchen.clamp(15, 0, 10), 10)

    def test_moving_average(self):
        self.assertEqual(kitchen.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(kitchen.moving_average([5], 1), [5.0])
        self.assertEqual(kitchen.moving_average([1, 2, 3], 3), [2.0])
