import unittest

from tally.tickets import count_words
from tally import tickets


class Tickets(unittest.TestCase):
    def test_count_words(self):
        self.assertEqual(count_words('a b'), 2)
        self.assertEqual(count_words('  tea  and   milk '), 3)
        self.assertEqual(count_words(''), 0)

    def test_rle(self):
        self.assertEqual(tickets.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(tickets.rle(''), [])
