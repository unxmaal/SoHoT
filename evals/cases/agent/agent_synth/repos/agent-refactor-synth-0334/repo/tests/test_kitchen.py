import unittest

from harbor import kitchen


class Kitchen(unittest.TestCase):
    def test_berth_row(self):
        self.assertEqual(kitchen.berth_row([1, 2, 3, 4], 2), {'berth_row': [1.5, 2.5, 3.5]})
        self.assertEqual(kitchen.berth_row([5], 1), {'berth_row': [5.0]})

    def test_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')
