import unittest

from meadow import survey


class Survey(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(survey.parse_duration('1h30m'), 5400)
        self.assertEqual(survey.parse_duration('45s'), 45)

    def test_chunk(self):
        self.assertEqual(survey.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(survey.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_top_n(self):
        self.assertEqual(survey.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(survey.top_n({'a': 1}, 5), ['a'])
