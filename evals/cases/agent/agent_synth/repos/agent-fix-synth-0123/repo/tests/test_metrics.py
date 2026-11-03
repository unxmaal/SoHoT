import unittest

from depot import metrics


class Metrics(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(metrics.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(metrics.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])

    def test_truncate_words(self):
        self.assertEqual(metrics.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(metrics.truncate_words('tea time', 2), 'tea time')
