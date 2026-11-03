import unittest

from foundry import tickets


class Tickets(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(tickets.grade(95), 'A')
        self.assertEqual(tickets.grade(90), 'A')

    def test_weighted_mean(self):
        self.assertEqual(tickets.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(tickets.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(tickets.weighted_mean([4], [2]), 4.0)
