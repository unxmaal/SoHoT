import unittest

from meadow import tickets


class Tickets(unittest.TestCase):
    def test_crate_row(self):
        self.assertEqual(tickets.crate_row([(1, 3), (3, 5)]), {'crate_row': [(1, 5)]})
        self.assertEqual(tickets.crate_row([(5, 6), (1, 2)]), {'crate_row': [(1, 2), (5, 6)]})

    def test_paginate(self):
        self.assertEqual(tickets.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(tickets.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
