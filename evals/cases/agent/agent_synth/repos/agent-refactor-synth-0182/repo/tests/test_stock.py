import unittest

from depot.stock import grade


class Stock(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(grade(95), 'A')
        self.assertEqual(grade(90), 'A')
        self.assertEqual(grade(85), 'B')
