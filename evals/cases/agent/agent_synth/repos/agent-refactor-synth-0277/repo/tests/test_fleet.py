import unittest

from orchard import fleet


class Fleet(unittest.TestCase):
    def test_deck_total(self):
        self.assertEqual(fleet.deck_total(5, [0, 5, 10]), {'deck_total': 2})
        self.assertEqual(fleet.deck_total(-1, [0, 5, 10]), {'deck_total': 0})

    def test_clamp(self):
        self.assertEqual(fleet.clamp(5, 0, 10), 5)
        self.assertEqual(fleet.clamp(-3, 0, 10), 0)

    def test_snake_case(self):
        self.assertEqual(fleet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(fleet.snake_case('plain'), 'plain')
