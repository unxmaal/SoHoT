import unittest

from foundry import metrics


class Metrics(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(metrics.parse_duration('1h30m'), 5400)
        self.assertEqual(metrics.parse_duration('45s'), 45)
        self.assertEqual(metrics.parse_duration('2h'), 7200)

    def test_paginate(self):
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])

    def test_snake_case(self):
        self.assertEqual(metrics.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(metrics.snake_case('plain'), 'plain')
        self.assertEqual(metrics.snake_case('A'), 'a')
