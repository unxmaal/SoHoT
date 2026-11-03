import unittest

from granary import orders


class Orders(unittest.TestCase):
    def test_deck_row(self):
        self.assertEqual(orders.deck_row('the quick brown fox', 2), {'deck_row': 'the quick...'})
        self.assertEqual(orders.deck_row('tea time', 2), {'deck_row': 'tea time'})

    def test_top_n(self):
        self.assertEqual(orders.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(orders.top_n({'a': 1}, 5), ['a'])

    def test_clamp(self):
        self.assertEqual(orders.clamp(5, 0, 10), 5)
        self.assertEqual(orders.clamp(-3, 0, 10), 0)
