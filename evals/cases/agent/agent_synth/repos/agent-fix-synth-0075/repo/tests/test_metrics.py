import unittest

from harbor import metrics


class Metrics(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(metrics.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(metrics.truncate_words('tea time', 2), 'tea time')

    def test_dedupe(self):
        self.assertEqual(metrics.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(metrics.dedupe(['b', 'a', 'b']), ['b', 'a'])
