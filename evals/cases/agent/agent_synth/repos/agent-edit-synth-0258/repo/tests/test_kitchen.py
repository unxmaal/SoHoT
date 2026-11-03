import unittest

from quarry import kitchen


class Kitchen(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(kitchen.is_leap(2024), True)
        self.assertEqual(kitchen.is_leap(1900), False)
        self.assertEqual(kitchen.is_leap(2000), True)

    def test_grade(self):
        self.assertEqual(kitchen.grade(95), 'A')
        self.assertEqual(kitchen.grade(90), 'A')
        self.assertEqual(kitchen.grade(85), 'B')
