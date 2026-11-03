import unittest

from depot import tickets


class Tickets(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(tickets.percent_change(50, 75), 50.0)
        self.assertEqual(tickets.percent_change(200, 150), -25.0)

    def test_invert(self):
        self.assertEqual(tickets.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(tickets.invert({}), {})

    def test_word_count(self):
        self.assertEqual(tickets.word_count('a b'), 2)
        self.assertEqual(tickets.word_count('  tea  and   milk '), 3)
