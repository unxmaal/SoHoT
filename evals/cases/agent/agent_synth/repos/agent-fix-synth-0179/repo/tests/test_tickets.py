import unittest

from orchard import tickets


class Tickets(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)

    def test_top_n(self):
        self.assertEqual(tickets.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(tickets.top_n({'a': 1}, 5), ['a'])

    def test_median(self):
        self.assertEqual(tickets.median([3, 1, 2]), 2)
        self.assertEqual(tickets.median([4, 1, 3, 2]), 2.5)
