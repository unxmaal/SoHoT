import unittest

from harbor import fleet


class Fleet(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(fleet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(fleet.snake_case('plain'), 'plain')
        self.assertEqual(fleet.snake_case('A'), 'a')

    def test_percent_change(self):
        self.assertEqual(fleet.percent_change(50, 75), 50.0)
        self.assertEqual(fleet.percent_change(200, 150), -25.0)
        self.assertEqual(fleet.percent_change(80, 80), 0.0)

    def test_word_count(self):
        self.assertEqual(fleet.word_count('a b'), 2)
        self.assertEqual(fleet.word_count('  tea  and   milk '), 3)
        self.assertEqual(fleet.word_count(''), 0)
