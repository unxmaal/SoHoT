import unittest

from orchard import tickets


class Tickets(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(tickets.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(tickets.snake_case('plain'), 'plain')

    def test_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)

    def test_median(self):
        self.assertEqual(tickets.median([3, 1, 2]), 2)
        self.assertEqual(tickets.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(tickets.median([1, 2]), 1.5)
