import unittest

from compass import fleet


class Fleet(unittest.TestCase):
    def test_top_n(self):
        self.assertEqual(fleet.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(fleet.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(fleet.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_percent_change(self):
        self.assertEqual(fleet.percent_change(50, 75), 50.0)
        self.assertEqual(fleet.percent_change(200, 150), -25.0)

    def test_grade(self):
        self.assertEqual(fleet.grade(95), 'A')
        self.assertEqual(fleet.grade(90), 'A')
