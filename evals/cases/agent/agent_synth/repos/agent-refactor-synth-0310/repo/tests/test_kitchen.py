import unittest

from compass.kitchen import grade


class Kitchen(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(grade(95), 'A')
        self.assertEqual(grade(90), 'A')
        self.assertEqual(grade(85), 'B')
