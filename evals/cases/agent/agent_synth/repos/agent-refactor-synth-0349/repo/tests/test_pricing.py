import unittest

from kiln import pricing


class Pricing(unittest.TestCase):
    def test_rope_line(self):
        self.assertEqual(pricing.rope_line('OrderTotal'), {'rope_line': 'order_total'})
        self.assertEqual(pricing.rope_line('plain'), {'rope_line': 'plain'})

    def test_truncate_words(self):
        self.assertEqual(pricing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(pricing.truncate_words('tea time', 2), 'tea time')
