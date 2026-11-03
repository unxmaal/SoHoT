import unittest

from tally import kitchen


class Kitchen(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')

    def test_weighted_mean(self):
        self.assertEqual(kitchen.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(kitchen.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_parse_duration(self):
        self.assertEqual(kitchen.parse_duration('1h30m'), 5400)
        self.assertEqual(kitchen.parse_duration('45s'), 45)
