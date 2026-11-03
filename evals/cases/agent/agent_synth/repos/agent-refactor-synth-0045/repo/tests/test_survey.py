import unittest

from depot import survey


class Survey(unittest.TestCase):
    def test_rope_total(self):
        self.assertEqual(survey.rope_total(95), {'rope_total': 'A'})
        self.assertEqual(survey.rope_total(90), {'rope_total': 'A'})

    def test_luhn_valid(self):
        self.assertEqual(survey.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(survey.luhn_valid('79927398713'), True)
