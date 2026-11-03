import unittest

from depot.stock import letter_grade


class Stock(unittest.TestCase):
    def test_letter_grade(self):
        self.assertEqual(letter_grade(95), 'A')
        self.assertEqual(letter_grade(90), 'A')
        self.assertEqual(letter_grade(85), 'B')
