import unittest

from granary import tickets


class Tickets(unittest.TestCase):
    def test_anchor_line(self):
        self.assertEqual(tickets.anchor_line(5, 0, 10), {'anchor_line': 5})
        self.assertEqual(tickets.anchor_line(-3, 0, 10), {'anchor_line': 0})

    def test_moving_average(self):
        self.assertEqual(tickets.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(tickets.moving_average([5], 1), [5.0])

    def test_grade(self):
        self.assertEqual(tickets.grade(95), 'A')
        self.assertEqual(tickets.grade(90), 'A')
