import unittest

from kiln import metrics


class Metrics(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(metrics.format_cents(0), '$0.00')
        self.assertEqual(metrics.format_cents(123456), '$1,234.56')
        self.assertEqual(metrics.format_cents(-105), '-$1.05')

    def test_paginate(self):
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
