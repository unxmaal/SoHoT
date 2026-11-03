import unittest

from wharf import tickets


class Tickets(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(tickets.word_count('a b'), 2)
        self.assertEqual(tickets.word_count('  tea  and   milk '), 3)
        self.assertEqual(tickets.word_count(''), 0)

    def test_invert(self):
        self.assertEqual(tickets.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(tickets.invert({}), {})
        self.assertEqual(tickets.invert({'x': 'y'}), {'y': ['x']})

    def test_top_n(self):
        self.assertEqual(tickets.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(tickets.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(tickets.top_n({}, 2), [])
