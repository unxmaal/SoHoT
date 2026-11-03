import unittest

from granary import pricing


class Pricing(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(pricing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(pricing.truncate_words('tea time', 2), 'tea time')

    def test_running_total(self):
        self.assertEqual(pricing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(pricing.running_total([]), [])
