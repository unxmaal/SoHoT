import unittest

from tally.metrics import format_cents
from tally import metrics


class Metrics(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(format_cents(0), '$0.00')
        self.assertEqual(format_cents(123456), '$1,234.56')
        self.assertEqual(format_cents(-105), '-$1.05')

    def test_top_n(self):
        self.assertEqual(metrics.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(metrics.top_n({'a': 1}, 5), ['a'])
