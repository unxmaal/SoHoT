import unittest

from durations import parse_duration


class Durations(unittest.TestCase):
    def test_single(self):
        self.assertEqual(parse_duration("45s"), 45)

    def test_combined(self):
        self.assertEqual(parse_duration("1h30m"), 5400)
