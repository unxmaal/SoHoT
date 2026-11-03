import unittest

from quarry import tickets


class Tickets(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(tickets.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(tickets.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(tickets.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])

    def test_luhn_valid(self):
        self.assertEqual(tickets.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(tickets.luhn_valid('79927398713'), True)
        self.assertEqual(tickets.luhn_valid('79927398710'), False)
