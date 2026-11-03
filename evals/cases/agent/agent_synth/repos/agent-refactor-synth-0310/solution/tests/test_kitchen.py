import unittest

from compass.kitchen import letter_grade


class Kitchen(unittest.TestCase):
    def test_letter_grade(self):
        self.assertEqual(letter_grade(95), 'A')
        self.assertEqual(letter_grade(90), 'A')
        self.assertEqual(letter_grade(85), 'B')
