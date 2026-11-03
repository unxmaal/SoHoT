import unittest

from tally.tickets import word_count
from tally import tickets


class Tickets(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(word_count('a b'), 2)
        self.assertEqual(word_count('  tea  and   milk '), 3)
        self.assertEqual(word_count(''), 0)

    def test_rle(self):
        self.assertEqual(tickets.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(tickets.rle(''), [])
