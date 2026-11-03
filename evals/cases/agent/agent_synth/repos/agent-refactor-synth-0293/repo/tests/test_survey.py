import unittest

from quarry import survey


class Survey(unittest.TestCase):
    def test_cargo_check(self):
        self.assertEqual(survey.cargo_check('4539 1488 0343 6467'), {'cargo_check': True})
        self.assertEqual(survey.cargo_check('79927398713'), {'cargo_check': True})

    def test_bucket(self):
        self.assertEqual(survey.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(survey.bucket(-1, [0, 5, 10]), 0)
