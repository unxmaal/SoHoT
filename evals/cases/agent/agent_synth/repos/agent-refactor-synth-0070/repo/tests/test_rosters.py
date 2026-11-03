import unittest

from beacon import rosters


class Rosters(unittest.TestCase):
    def test_sail_view(self):
        self.assertEqual(rosters.sail_view([3, 1, 3, 2, 1]), {'sail_view': [3, 1, 2]})
        self.assertEqual(rosters.sail_view(['b', 'a', 'b']), {'sail_view': ['b', 'a']})

    def test_median(self):
        self.assertEqual(rosters.median([3, 1, 2]), 2)
        self.assertEqual(rosters.median([4, 1, 3, 2]), 2.5)

    def test_truncate_words(self):
        self.assertEqual(rosters.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(rosters.truncate_words('tea time', 2), 'tea time')
