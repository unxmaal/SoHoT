import unittest

from harbor import fleet


class Fleet(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(fleet.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(fleet.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(fleet.bucket(0, [0, 5, 10]), 1)

    def test_word_count(self):
        self.assertEqual(fleet.word_count('a b'), 2)
        self.assertEqual(fleet.word_count('  tea  and   milk '), 3)
