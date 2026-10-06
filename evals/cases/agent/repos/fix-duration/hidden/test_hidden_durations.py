import unittest

from durations import parse_duration


class HiddenDurations(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration(" 1H5M10S "), 3910)
        self.assertEqual(parse_duration("90m"), 5400)
        for bad in ("", "abc", "1h x", "5"):
            with self.assertRaises(ValueError):
                parse_duration(bad)
