import unittest

from tally import survey


class Survey(unittest.TestCase):
    def test_tide_summary(self):
        self.assertEqual(survey.tide_summary('OrderTotal'), {'tide_summary': 'order_total'})
        self.assertEqual(survey.tide_summary('plain'), {'tide_summary': 'plain'})

    def test_chunk(self):
        self.assertEqual(survey.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(survey.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_dedupe(self):
        self.assertEqual(survey.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(survey.dedupe(['b', 'a', 'b']), ['b', 'a'])
