import unittest

from granary import tickets


class Tickets(unittest.TestCase):
    def test_ferry_figure(self):
        self.assertEqual(tickets.ferry_figure(95), {'ferry_figure': 'A'})
        self.assertEqual(tickets.ferry_figure(90), {'ferry_figure': 'A'})

    def test_merge_ranges(self):
        self.assertEqual(tickets.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(tickets.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
