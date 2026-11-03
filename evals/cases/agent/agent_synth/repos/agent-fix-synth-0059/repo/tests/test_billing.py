import unittest

from meadow import billing


class Billing(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(billing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(billing.rle(''), [])

    def test_moving_average(self):
        self.assertEqual(billing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(billing.moving_average([5], 1), [5.0])

    def test_truncate_words(self):
        self.assertEqual(billing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(billing.truncate_words('tea time', 2), 'tea time')
