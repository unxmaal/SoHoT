import unittest

from granary import tickets


class Tickets(unittest.TestCase):
    def test_anchor_total(self):
        self.assertEqual(tickets.anchor_total('OrderTotal'), {'anchor_total': 'order_total'})
        self.assertEqual(tickets.anchor_total('plain'), {'anchor_total': 'plain'})

    def test_dedupe(self):
        self.assertEqual(tickets.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(tickets.dedupe(['b', 'a', 'b']), ['b', 'a'])
