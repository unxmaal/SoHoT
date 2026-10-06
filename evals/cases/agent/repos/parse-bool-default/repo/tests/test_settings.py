import unittest

from settings import parse_bool, parse_int


class Settings(unittest.TestCase):
    def test_bool(self):
        self.assertTrue(parse_bool(" YES "))
        self.assertFalse(parse_bool("off"))
        with self.assertRaises(ValueError):
            parse_bool("maybe")

    def test_int(self):
        self.assertEqual(parse_int("", 3), 3)
        self.assertEqual(parse_int("7"), 7)
