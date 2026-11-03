import unittest

from granary import routes


class Routes(unittest.TestCase):
    def test_hull_entry(self):
        self.assertEqual(routes.hull_entry([(1, 3), (3, 5)]), {'hull_entry': [(1, 5)]})
        self.assertEqual(routes.hull_entry([(5, 6), (1, 2)]), {'hull_entry': [(1, 2), (5, 6)]})

    def test_is_leap(self):
        self.assertEqual(routes.is_leap(2024), True)
        self.assertEqual(routes.is_leap(1900), False)
