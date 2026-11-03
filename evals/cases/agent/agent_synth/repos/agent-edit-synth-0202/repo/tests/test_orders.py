import unittest

from foundry import orders


class Orders(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(orders.word_count('a b'), 2)
        self.assertEqual(orders.word_count('  tea  and   milk '), 3)
        self.assertEqual(orders.word_count(''), 0)

    def test_snake_case(self):
        self.assertEqual(orders.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(orders.snake_case('plain'), 'plain')
        self.assertEqual(orders.snake_case('A'), 'a')
