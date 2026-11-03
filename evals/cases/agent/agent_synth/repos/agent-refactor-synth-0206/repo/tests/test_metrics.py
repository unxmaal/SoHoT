import unittest

from mill import metrics


class Metrics(unittest.TestCase):
    def test_crate_row(self):
        self.assertEqual(metrics.crate_row([3, 1, 2]), {'crate_row': 2})
        self.assertEqual(metrics.crate_row([4, 1, 3, 2]), {'crate_row': 2.5})

    def test_parse_duration(self):
        self.assertEqual(metrics.parse_duration('1h30m'), 5400)
        self.assertEqual(metrics.parse_duration('45s'), 45)
