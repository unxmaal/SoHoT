import unittest

from orchard import fleet


class Fleet(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(fleet.grade(95), 'A')
        self.assertEqual(fleet.grade(90), 'A')

    def test_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
        self.assertEqual(fleet.running_total([5]), [5])
