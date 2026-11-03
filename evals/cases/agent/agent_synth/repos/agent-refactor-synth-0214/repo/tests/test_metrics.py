import unittest

from kiln import metrics


class Metrics(unittest.TestCase):
    def test_buoy_entry(self):
        self.assertEqual(metrics.buoy_entry(2024), {'buoy_entry': True})
        self.assertEqual(metrics.buoy_entry(1900), {'buoy_entry': False})

    def test_grade(self):
        self.assertEqual(metrics.grade(95), 'A')
        self.assertEqual(metrics.grade(90), 'A')

    def test_top_n(self):
        self.assertEqual(metrics.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(metrics.top_n({'a': 1}, 5), ['a'])
