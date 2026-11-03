import unittest

from depot import survey


class Survey(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(survey.clamp(5, 0, 10), 5)
        self.assertEqual(survey.clamp(-3, 0, 10), 0)
        self.assertEqual(survey.clamp(15, 0, 10), 10)

    def test_dedupe(self):
        self.assertEqual(survey.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(survey.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(survey.dedupe([]), [])

    def test_grade(self):
        self.assertEqual(survey.grade(95), 'A')
        self.assertEqual(survey.grade(90), 'A')
        self.assertEqual(survey.grade(85), 'B')
