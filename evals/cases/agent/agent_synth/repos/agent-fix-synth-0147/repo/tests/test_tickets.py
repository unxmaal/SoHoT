import unittest

from compass import tickets


class Tickets(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(tickets.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(tickets.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_snake_case(self):
        self.assertEqual(tickets.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(tickets.snake_case('plain'), 'plain')
