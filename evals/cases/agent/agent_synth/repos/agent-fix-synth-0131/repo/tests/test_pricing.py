import unittest

from granary import pricing


class Pricing(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(pricing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(pricing.truncate_words('tea time', 2), 'tea time')

    def test_weighted_mean(self):
        self.assertEqual(pricing.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(pricing.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_chunk(self):
        self.assertEqual(pricing.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(pricing.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
