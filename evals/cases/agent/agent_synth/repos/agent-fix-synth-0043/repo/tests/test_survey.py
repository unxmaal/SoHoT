import unittest

from meadow import survey


class Survey(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(survey.grade(95), 'A')
        self.assertEqual(survey.grade(90), 'A')

    def test_merge_ranges(self):
        self.assertEqual(survey.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(survey.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
