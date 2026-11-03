import unittest

from granary.textual import truncate_words
from granary import tickets


class Tickets(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(truncate_words('tea time', 2), 'tea time')
        self.assertEqual(truncate_words('', 3), '')

    def test_weighted_mean(self):
        self.assertEqual(tickets.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(tickets.weighted_mean([10, 20], [1, 3]), 17.5)
