import unittest

from atlas.archive import parse_duration
from atlas import archive


class Archive(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(parse_duration('1h30m'), 5400)
        self.assertEqual(parse_duration('45s'), 45)
        self.assertEqual(parse_duration('2h'), 7200)

    def test_percent_change(self):
        self.assertEqual(archive.percent_change(50, 75), 50.0)
        self.assertEqual(archive.percent_change(200, 150), -25.0)
