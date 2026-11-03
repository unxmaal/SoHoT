import unittest

from foundry import tickets


class Tickets(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(tickets.is_leap(2024), True)
        self.assertEqual(tickets.is_leap(1900), False)

    def test_merge_ranges(self):
        self.assertEqual(tickets.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(tickets.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])

    def test_clamp(self):
        self.assertEqual(tickets.clamp(5, 0, 10), 5)
        self.assertEqual(tickets.clamp(-3, 0, 10), 0)
