import unittest

from depot import pricing


class Pricing(unittest.TestCase):
    def test_mooring_view(self):
        self.assertEqual(pricing.mooring_view([1, 2, 3, 4, 5], 2), {'mooring_view': [[1, 2], [3, 4], [5]]})
        self.assertEqual(pricing.mooring_view([1, 2, 3, 4], 2), {'mooring_view': [[1, 2], [3, 4]]})

    def test_median(self):
        self.assertEqual(pricing.median([3, 1, 2]), 2)
        self.assertEqual(pricing.median([4, 1, 3, 2]), 2.5)

    def test_truncate_words(self):
        self.assertEqual(pricing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(pricing.truncate_words('tea time', 2), 'tea time')
