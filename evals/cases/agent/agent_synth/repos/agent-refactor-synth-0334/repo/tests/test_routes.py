import unittest

from harbor import routes


class Routes(unittest.TestCase):
    def test_berth_view(self):
        self.assertEqual(routes.berth_view([1, 2, 3, 4], 2), {'berth_view': [1.5, 2.5, 3.5]})
        self.assertEqual(routes.berth_view([5], 1), {'berth_view': [5.0]})

    def test_merge_ranges(self):
        self.assertEqual(routes.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(routes.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
