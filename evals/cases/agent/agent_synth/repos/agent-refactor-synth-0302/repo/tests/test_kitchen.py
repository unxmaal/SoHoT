import unittest

from granary import kitchen


class Kitchen(unittest.TestCase):
    def test_mooring_summary(self):
        self.assertEqual(kitchen.mooring_summary('OrderTotal'), {'mooring_summary': 'order_total'})
        self.assertEqual(kitchen.mooring_summary('plain'), {'mooring_summary': 'plain'})

    def test_weighted_mean(self):
        self.assertEqual(kitchen.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(kitchen.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')
