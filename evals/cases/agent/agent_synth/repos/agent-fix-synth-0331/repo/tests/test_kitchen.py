import unittest

from beacon import kitchen


class Kitchen(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(kitchen.is_leap(2024), True)
        self.assertEqual(kitchen.is_leap(1900), False)
        self.assertEqual(kitchen.is_leap(2100), False)

    def test_grade(self):
        self.assertEqual(kitchen.grade(95), 'A')
        self.assertEqual(kitchen.grade(90), 'A')

    def test_bucket(self):
        self.assertEqual(kitchen.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(kitchen.bucket(-1, [0, 5, 10]), 0)
