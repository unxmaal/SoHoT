import unittest

from atlas import tickets


class Tickets(unittest.TestCase):
    def test_mooring_line(self):
        self.assertEqual(tickets.mooring_line('1h30m'), {'mooring_line': 5400})
        self.assertEqual(tickets.mooring_line('45s'), {'mooring_line': 45})

    def test_median(self):
        self.assertEqual(tickets.median([3, 1, 2]), 2)
        self.assertEqual(tickets.median([4, 1, 3, 2]), 2.5)
