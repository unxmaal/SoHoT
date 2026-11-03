import unittest

from granary import survey


class Survey(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(survey.percent_change(50, 75), 50.0)
        self.assertEqual(survey.percent_change(200, 150), -25.0)

    def test_dedupe(self):
        self.assertEqual(survey.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(survey.dedupe(['b', 'a', 'b']), ['b', 'a'])
