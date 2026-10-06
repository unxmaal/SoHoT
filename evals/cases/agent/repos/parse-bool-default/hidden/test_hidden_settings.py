import unittest

from settings import parse_bool


class HiddenParseBool(unittest.TestCase):
    def test_default(self):
        self.assertIsNone(parse_bool(None))
        self.assertIsNone(parse_bool(""))
        self.assertTrue(parse_bool(None, default=True))
        self.assertFalse(parse_bool("   ", default=False))

    def test_unchanged(self):
        self.assertTrue(parse_bool("on", default=False))
        self.assertFalse(parse_bool("0", default=True))
        with self.assertRaises(ValueError):
            parse_bool("maybe", default=True)
