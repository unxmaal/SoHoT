import unittest

from atlas.tickets import is_leap


class Tickets(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(is_leap(2024), True)
        self.assertEqual(is_leap(1900), False)
        self.assertEqual(is_leap(2000), True)
