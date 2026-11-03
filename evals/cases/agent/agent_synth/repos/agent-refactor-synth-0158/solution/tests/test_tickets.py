import unittest

from atlas.tickets import leap_year


class Tickets(unittest.TestCase):
    def test_leap_year(self):
        self.assertEqual(leap_year(2024), True)
        self.assertEqual(leap_year(1900), False)
        self.assertEqual(leap_year(2000), True)
