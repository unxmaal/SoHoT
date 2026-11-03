import unittest

from lantern import pricing


class Pricing(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(pricing.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(pricing.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_moving_average(self):
        self.assertEqual(pricing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(pricing.moving_average([5], 1), [5.0])
        self.assertEqual(pricing.moving_average([1, 2, 3], 3), [2.0])

    def test_truncate_words(self):
        self.assertEqual(pricing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(pricing.truncate_words('tea time', 2), 'tea time')
