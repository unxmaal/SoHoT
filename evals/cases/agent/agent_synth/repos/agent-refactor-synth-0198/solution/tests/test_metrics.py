import unittest

from tally.metrics import money
from tally import metrics


class Metrics(unittest.TestCase):
    def test_money(self):
        self.assertEqual(money(0), '$0.00')
        self.assertEqual(money(123456), '$1,234.56')
        self.assertEqual(money(-105), '-$1.05')

    def test_top_n(self):
        self.assertEqual(metrics.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(metrics.top_n({'a': 1}, 5), ['a'])
