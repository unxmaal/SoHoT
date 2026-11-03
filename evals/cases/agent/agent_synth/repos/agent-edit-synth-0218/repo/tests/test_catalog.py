import unittest

from depot import catalog


class Catalog(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(catalog.percent_change(50, 75), 50.0)
        self.assertEqual(catalog.percent_change(200, 150), -25.0)
        self.assertEqual(catalog.percent_change(80, 80), 0.0)

    def test_grade(self):
        self.assertEqual(catalog.grade(95), 'A')
        self.assertEqual(catalog.grade(90), 'A')
        self.assertEqual(catalog.grade(85), 'B')

    def test_running_total(self):
        self.assertEqual(catalog.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(catalog.running_total([]), [])
        self.assertEqual(catalog.running_total([5]), [5])
