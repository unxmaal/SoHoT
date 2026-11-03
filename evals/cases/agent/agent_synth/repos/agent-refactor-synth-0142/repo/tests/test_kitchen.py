import unittest

from kiln import kitchen


class Kitchen(unittest.TestCase):
    def test_sail_view(self):
        self.assertEqual(kitchen.sail_view('the quick brown fox', 2), {'sail_view': 'the quick...'})
        self.assertEqual(kitchen.sail_view('tea time', 2), {'sail_view': 'tea time'})

    def test_merge_ranges(self):
        self.assertEqual(kitchen.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(kitchen.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
