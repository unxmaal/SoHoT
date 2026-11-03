import unittest

from compass.core_math import clamp
from compass import tickets


class Tickets(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-3, 0, 10), 0)
        self.assertEqual(clamp(15, 0, 10), 10)

    def test_running_total(self):
        self.assertEqual(tickets.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(tickets.running_total([]), [])
