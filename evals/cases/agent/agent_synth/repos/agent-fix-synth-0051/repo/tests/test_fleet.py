import unittest

from depot import fleet


class Fleet(unittest.TestCase):
    def test_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
        self.assertEqual(fleet.running_total([5]), [5])

    def test_luhn_valid(self):
        self.assertEqual(fleet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(fleet.luhn_valid('79927398713'), True)

    def test_grade(self):
        self.assertEqual(fleet.grade(95), 'A')
        self.assertEqual(fleet.grade(90), 'A')
