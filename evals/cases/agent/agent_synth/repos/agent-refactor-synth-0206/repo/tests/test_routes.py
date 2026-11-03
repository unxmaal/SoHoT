import unittest

from mill import routes


class Routes(unittest.TestCase):
    def test_hull_summary(self):
        self.assertEqual(routes.hull_summary([3, 1, 2]), {'hull_summary': 2})
        self.assertEqual(routes.hull_summary([4, 1, 3, 2]), {'hull_summary': 2.5})

    def test_merge_ranges(self):
        self.assertEqual(routes.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(routes.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
