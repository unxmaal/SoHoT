import unittest

from compass import rosters


class Rosters(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(rosters.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(rosters.bucket(-1, [0, 5, 10]), 0)

    def test_word_count(self):
        self.assertEqual(rosters.word_count('a b'), 2)
        self.assertEqual(rosters.word_count('  tea  and   milk '), 3)

    def test_snake_case(self):
        self.assertEqual(rosters.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(rosters.snake_case('plain'), 'plain')
