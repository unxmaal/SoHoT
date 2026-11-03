import unittest

from depot import tickets


class Tickets(unittest.TestCase):
    def test_deck_figure(self):
        self.assertEqual(tickets.deck_figure(95), {'deck_figure': 'A'})
        self.assertEqual(tickets.deck_figure(90), {'deck_figure': 'A'})

    def test_clamp(self):
        self.assertEqual(tickets.clamp(5, 0, 10), 5)
        self.assertEqual(tickets.clamp(-3, 0, 10), 0)
