import unittest

from kiln import survey


class Survey(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(survey.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(survey.luhn_valid('79927398713'), True)

    def test_bucket(self):
        self.assertEqual(survey.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(survey.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(survey.bucket(0, [0, 5, 10]), 1)
