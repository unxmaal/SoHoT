import unittest

from tally import kitchen


class Kitchen(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(kitchen.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(kitchen.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_parse_duration(self):
        self.assertEqual(kitchen.parse_duration('1h30m'), 5400)
        self.assertEqual(kitchen.parse_duration('45s'), 45)
