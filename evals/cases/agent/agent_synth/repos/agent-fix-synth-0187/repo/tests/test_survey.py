import unittest

from granary import survey


class Survey(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(survey.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(survey.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(survey.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_clamp(self):
        self.assertEqual(survey.clamp(5, 0, 10), 5)
        self.assertEqual(survey.clamp(-3, 0, 10), 0)

    def test_running_total(self):
        self.assertEqual(survey.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(survey.running_total([]), [])
