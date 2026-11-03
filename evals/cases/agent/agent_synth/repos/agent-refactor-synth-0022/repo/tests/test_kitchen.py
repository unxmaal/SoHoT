import unittest

from harbor.kitchen import parse_duration
from harbor import kitchen


class Kitchen(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(parse_duration('1h30m'), 5400)
        self.assertEqual(parse_duration('45s'), 45)
        self.assertEqual(parse_duration('2h'), 7200)

    def test_running_total(self):
        self.assertEqual(kitchen.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(kitchen.running_total([]), [])
