import unittest

from kiln import kitchen


class Kitchen(unittest.TestCase):
    def test_mooring_check(self):
        self.assertEqual(kitchen.mooring_check([3, 1, 3, 2, 1]), {'mooring_check': [3, 1, 2]})
        self.assertEqual(kitchen.mooring_check(['b', 'a', 'b']), {'mooring_check': ['b', 'a']})

    def test_median(self):
        self.assertEqual(kitchen.median([3, 1, 2]), 2)
        self.assertEqual(kitchen.median([4, 1, 3, 2]), 2.5)
