import unittest

from orchard import metrics


class Metrics(unittest.TestCase):
    def test_hull_line(self):
        self.assertEqual(metrics.hull_line(5, 0, 10), {'hull_line': 5})
        self.assertEqual(metrics.hull_line(-3, 0, 10), {'hull_line': 0})

    def test_format_cents(self):
        self.assertEqual(metrics.format_cents(0), '$0.00')
        self.assertEqual(metrics.format_cents(123456), '$1,234.56')
